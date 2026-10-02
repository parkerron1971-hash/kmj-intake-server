"""Local synthetic fixture. Never forwards submissions or queries a database."""
import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.parse import urlsplit,parse_qs
from form_page_renderer import render_form_page
from events_rsvp_router import render_events_page
ROOT=pathlib.Path(__file__).resolve().parents[1]
BIZ={'id':'preview','name':'KMJ Creative Solutions','settings':{'brand_kit':{'colors':{'accent':'#009133'},'font_body':'Open Sans','font_heading':'Montserrat'}}}
SITE={'business_id':'preview','status':'published','html_content':'<style>'+(ROOT/'sites/kmj-creative-solutions/site.css').read_text()+'</style>'}
FORM={'id':'preview-form','business_id':'preview','name':'Embrace the Shift Workshop Registration','form_type':'event','settings':{'description':'Complete the registration form below.','confirmation_message':'Thank you. Your registration has been received.'},'fields':[{'name':'name','label':'Full name','type':'text','required':True},{'name':'email','label':'Email address','type':'email','required':True},{'name':'phone','label':'Phone number','type':'phone'},{'name':'notes','label':'Anything else we should know?','type':'textarea'},{'name':'heard','label':'How did you hear about us?','type':'select','options':['Friend','Website']},{'name':'updates','label':'Keep me posted','type':'checkbox'}]}
FORM['settings']['event_details']={'description':'A free workshop open to the public.','starts_at':'2026-10-13T19:00:00-04:00','timezone':'America/Detroit','location':'1084 Allen Avenue, Muskegon, MI 49442','admission':'Free and open to the public','include_flyer':False}
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if urlsplit(self.path).path=='/embed':
   page='<html><body style="margin:0"><iframe title="Registration" src="/form?embed=1" style="width:100%;height:800px;border:0"></iframe></body></html>'
  elif urlsplit(self.path).path=='/events':
   page=render_events_page(BIZ,[],'http://127.0.0.1:5176/events','preview',api_origin='http://127.0.0.1:5176',site=SITE)
  else:
   current_site={**SITE,'form_theme':{'surface':'#14120E','text_primary':'#F7F4EE','text_secondary':'#F7F4EE'}} if 'dark' in parse_qs(urlsplit(self.path).query) else SITE
   preview_form={**FORM,'settings':{**FORM['settings'],'event_details':{**FORM['settings']['event_details']}}}
   if 'flyer' in parse_qs(urlsplit(self.path).query):
    preview_form['settings']['event_details'].update(include_flyer=True,flyer_url='https://cdn.example.org/preview-flyer.svg')
   page=render_form_page(BIZ,preview_form,site=current_site,submit_url='/intake/submit',canonical_url='https://kmj-creative-solutions.mysolutionist.app/public/widget/form/preview',embedded=parse_qs(urlsplit(self.path).query).get('embed')==['1'])
  body=page.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_POST(self):self.send_error(405,'Preview only: no submissions are saved')
 def log_message(self,*a):pass
print('Synthetic form preview: http://127.0.0.1:5176',flush=True)
HTTPServer(('127.0.0.1',5176),Handler).serve_forever()
