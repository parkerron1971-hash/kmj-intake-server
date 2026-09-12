"""A checkout claim is not approval. Verify current DOM evidence before submit.

Generic supported checkout: visible item rows with one named quantity input per
planned line, a visible dollar total, and a recognizable final purchase control.
Ambiguous/unsupported layouts require manual completion; never guess a purchase.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from browser_controller import BrowserStopped, FIELD, VISIBLE_TEXT

PURCHASE = re.compile(r'\b(place\s+(?:the\s+)?order|pay(?:\s+now)?|buy(?:\s+now)?|confirm\s+(?:order|purchase)|complete\s+(?:order|purchase)|submit\s+order)\b',re.I)
QUANTITY = re.compile(r'\bqty\b|quantity',re.I)

CHECKOUT_TOOL = {'name':'review_checkout','description':
    'Required before placing an order. Use read_page(filter="all") to obtain references to each item row, its quantity input, the final dollar-total text and the final purchase button. The server verifies their current values against the plan. Never submit without an accepted review.',
    'input_schema':{'type':'object','properties':{
        'tab_id':{'type':'string'},'submit_ref':{'type':'string'},'total_ref':{'type':'string'},
        'items':{'type':'array','items':{'type':'object','properties':{
            'offering_id':{'type':'string'},'item_ref':{'type':'string'},'quantity_ref':{'type':'string'}},
            'required':['offering_id','item_ref','quantity_ref'],'additionalProperties':False}}},
        'required':['submit_ref','total_ref','items'],'additionalProperties':False}}


def quantity_field(el):
    attrs=el.evaluate(FIELD)
    return attrs['tag'] in ('input','select') and bool(QUANTITY.search(' '.join(str(attrs.get(k,'')) for k in ('name','id','label'))))


def amount(text):
    found=re.findall(r'(?<!sub)\b(?:grand\s+|order\s+)?total\b[^$\d]{0,20}\$\s*([\d,]+\.\d{2})(?!\d)',text,re.I)
    cents={int(v.replace(',','').replace('.','')) for v in found}
    if len(cents)!=1:
        raise BrowserStopped('The final checkout total is missing or ambiguous.')
    return cents.pop()


@dataclass(repr=False)
class CheckoutReview:
    page: object
    submit: object
    total_element: object
    lines: list
    cents: int
    host: str
    before_text: str
    approved: bool=False

    def validate(self, controller):
        controller._check_hosts()
        if self.page.url.split('/')[2] != self.host:
            raise BrowserStopped('The checkout host changed. Review checkout again.')
        for element in [self.submit,self.total_element,*[e for line in self.lines for e in line[:2]]]:
            if not element.evaluate('el => el.isConnected') or not element.is_visible():
                raise BrowserStopped('Checkout changed. Review checkout again.')
        if not PURCHASE.search(self.submit.evaluate(VISIBLE_TEXT) or self.submit.get_attribute('aria-label') or self.submit.get_attribute('value') or ''):
            raise BrowserStopped('The final purchase control changed.')
        if amount(self.total_element.evaluate(VISIBLE_TEXT))!=self.cents:
            raise BrowserStopped('The checkout total changed. Review checkout again.')
        seen=[]
        for item_element,qty_element,planned in self.lines:
            if not item_element.evaluate('(el,qty) => el.contains(qty)',qty_element):
                raise BrowserStopped('The quantity no longer belongs to its item.')
            text=item_element.evaluate(VISIBLE_TEXT).casefold()
            marker=str(planned.get('sku') or planned['name']).casefold()
            if not marker or marker not in text or len(text)>2000:
                raise BrowserStopped('The checkout item cannot be matched to the plan.')
            if not quantity_field(qty_element) or qty_element.input_value()!=str(planned['qty']):
                raise BrowserStopped('The checkout quantities differ from the approved plan.')
            line_quantities=[q for q in item_element.query_selector_all('input,select') if q.is_visible() and quantity_field(q)]
            if len(line_quantities)!=1:
                raise BrowserStopped('The checkout item row is ambiguous.')
            seen.append(qty_element)
        actual=[q for frame in self.page.frames for q in frame.query_selector_all('input,select')
                if q.is_visible() and quantity_field(q)]
        if len(actual)!=len(seen) or any(not any(q.evaluate('(el,other)=>el===other',known) for known in seen) for q in actual):
            raise BrowserStopped('There are additional or unverified quantities in the cart.')


def inspect_checkout(controller,plan,args):
    tid,page=controller._page(args)
    ref=lambda value:controller._element(tid,{'type':'ref','ref':value})
    planned={i['offering_id']:i for i in plan.get('items',[])}
    submitted=args.get('items')
    if (not planned or not isinstance(submitted,list) or len(submitted)!=len(planned)
            or {i.get('offering_id') for i in submitted}!=set(planned)):
        raise BrowserStopped('Checkout must contain exactly the planned items.')
    total=ref(args.get('total_ref'))
    review=CheckoutReview(page,ref(args.get('submit_ref')),total,
        [(ref(i.get('item_ref')),ref(i.get('quantity_ref')),planned[i['offering_id']]) for i in submitted],
        amount(total.evaluate(VISIBLE_TEXT)),page.url.split('/')[2],
        controller.scrubber.text(page.locator('body').evaluate(VISIBLE_TEXT)))
    review.validate(controller)
    return review


def action_element(controller,name,args):
    tid,page=controller._page(args)
    target=args.get('target')
    if name in ('type','key','hold_key'):
        return controller._focused(page)
    if isinstance(target,dict) and target.get('type')=='ref':
        return controller._element(tid,target)
    if isinstance(target,dict) and target.get('type')=='coordinate':
        point=controller._point(target)
        return page.evaluate_handle('([x,y])=>document.elementFromPoint(x,y)',list(point)).as_element()
    return None


def is_purchase_action(controller,name,args,element):
    if name not in {'left_click','double_click','triple_click','middle_click','right_click',
                    'left_mouse_down','left_mouse_up','left_click_drag','key','hold_key'}:
        return False
    if element is None:
        return False
    if name in ('key','hold_key'):
        if not re.search(r'enter|return|space',str(args.get('text','')),re.I):
            return False
        form=element.evaluate_handle('el=>el.form').as_element()
        if form:
            buttons=form.query_selector_all('button,input[type="submit"]')
            if any(PURCHASE.search(b.evaluate(VISIBLE_TEXT) or b.get_attribute('value') or '') for b in buttons):
                return True
    control=element.evaluate_handle('el=>el.closest("button,a,input,[role=button]") || el').as_element()
    text=control.evaluate(VISIBLE_TEXT) or control.get_attribute('aria-label') or control.get_attribute('value') or ''
    return bool(PURCHASE.search(text))
