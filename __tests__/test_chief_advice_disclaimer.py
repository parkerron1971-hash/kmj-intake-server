"""Reference estimates are not automatically legal or regulatory instructions."""
import json
import pytest
import chief_truth as truth

NOTICE = 'This is general guidance; confirm the applicable rule with the official source before acting.'


def clean(draft, refs, *, gaps=(), sources=None):
    claims = [{'text': text, 'kind': 'reference', 'source_id': '', 'quote': ''} for text in refs]
    claims += [{'text': text, 'kind': 'fact', 'source_id': '', 'quote': '', 'gap': 'No evidence'} for text in gaps]
    raw = json.dumps({'verdict': 'unsupported', 'claims': claims})
    return truth._clean_review_gaps(raw, draft, sources or {}, list(gaps), refs)


@pytest.mark.parametrize('draft,reference', [
    ('The first result is stronger proof. The bigger payoff comes over weeks. Treat that as an estimate, not a forecast.',
     'The bigger payoff comes over weeks'),
    ('Similar workshops typically run $75 to $120 per seat.',
     'Similar workshops typically run $75 to $120 per seat'),
    ('Testimonials help people understand the offer. Keep a steady outreach rhythm afterward.',
     'Testimonials help people understand the offer'),
    ('A founders price around $40 could help test demand. Treat the revenue as an estimate, not a forecast.',
     'A founders price around $40 could help test demand'),
    ('A rule of thumb is to keep the group small while testing the format.',
     'A rule of thumb is to keep the group small while testing the format'),
])
def test_marketing_advice_and_estimates_keep_substance_without_official_rule_footer(draft, reference):
    out, meta = clean(draft, [reference])
    assert out == draft
    assert NOTICE not in out and 'official source' not in out
    assert meta['references'] == [reference]  # still classified as general knowledge


def test_numeric_trim_then_reference_cleanup_retains_estimate_without_boilerplate():
    # The ordinary outcome discussion still flows after a genuinely unsupported
    # sentence is cut; its uncertainty wording is not stripped with the footer.
    draft = 'The bigger payoff comes over weeks. Treat that as an estimate, not a forecast. Demand is guaranteed.'
    out, meta = clean(draft, ['The bigger payoff comes over weeks'], gaps=['Demand is guaranteed.'])
    assert out == 'The bigger payoff comes over weeks. Treat that as an estimate, not a forecast.'
    assert meta['cuts'] == 1 and NOTICE not in out


@pytest.mark.parametrize('rule', [
    'The 990-N threshold is $50,000 in gross receipts.',
    'State law requires a license before offering this service.',
    'The tax filing deadline applies to this form.',
    'FTC regulations require advertising disclosures.',
    'Copyright applies to that image.',
    'Employers must retain payroll records for three years.',
    'HIPAA requires written authorization for this disclosure.',
    'Google prohibits incentivized reviews.',
    'Meta requires advertisers to disclose sponsored content.',
    'Employers are required to retain payroll records for three years.',
])
def test_genuine_public_rules_keep_the_existing_official_source_warning(rule):
    out, _ = clean(rule, [rule])
    assert out == rule + '\n\n' + NOTICE


def test_short_rule_excerpt_uses_its_surviving_sentence_for_context():
    draft = 'Under state law, registration is required before opening.'
    out, _ = clean(draft, ['registration is required before opening'])
    assert NOTICE in out


def test_unverified_published_source_keeps_a_source_caveat_without_inventing_a_rule():
    draft = 'According to a published study, short messages usually get more replies.'
    out, meta = clean(draft, [draft])
    assert "I haven't verified the cited source for that claim." in out
    assert NOTICE not in out and meta['references'] == [draft]


def test_cut_rule_does_not_attach_a_warning_to_surviving_marketing_advice():
    rule = 'Tax registration is required, but this location is exempt.'
    advice = 'The first outcome is a clearer offer.'
    out, _ = clean(rule + ' ' + advice, [rule, advice], gaps=[rule])
    # Trimming an unsupported whole rule sentence cannot leave its source warning.
    assert out == advice and NOTICE not in out


def test_business_figures_and_fabricated_citations_keep_existing_checks():
    text = 'Your revenue was $9,000.'
    raw = json.dumps({'verdict': 'supported', 'claims': [
        {'text': text, 'kind': 'reference', 'source_id': '', 'quote': ''}]})
    assert truth.assess_review(raw, text, {})[0] == 'unsupported'
    sources = {'web:https://example.invalid/study': {'kind': 'research', 'text': 'The sample was small.'}}
    raw = json.dumps({'verdict': 'supported', 'claims': [
        {'text': 'A study found better results.', 'kind': 'reference', 'source_id': next(iter(sources)),
         'quote': 'Invented quotation'}]})
    assert truth.assess_review(raw, 'A study found better results.', sources)[0] == 'unsupported'


def test_medical_dosing_retains_a_specific_verification_caveat():
    draft = 'Adults can take 400 mg of ibuprofen every six hours.'
    out, meta = clean(draft, [draft])
    assert out.startswith(draft)
    assert 'qualified clinician or an official medical source' in out
    assert meta['references'] == [draft]
