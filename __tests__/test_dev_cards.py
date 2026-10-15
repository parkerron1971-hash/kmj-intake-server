import io
import json
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from PIL import Image
import dev_cards as cards
import dev_kai
import dev_bridge
import dev_relay as store
from __tests__.dev_relay_fake import relay, run, D1, D2


def image(fmt='PNG', width=20):
    b=io.BytesIO();Image.new('RGB',(width,20),'red').save(b,format=fmt);return b.getvalue()


def upload(data, name='file.txt', mime='text/plain'):
    return UploadFile(io.BytesIO(data),filename=name,headers=Headers({'content-type':mime}))


def create(file=None, thumb=None, kind='file', auth='Bearer one', **meta):
    return run(cards.card_upload(json.dumps({'kind':kind,**meta}),file,thumb,auth))


def signed(monkeypatch):
    calls=[]
    async def sign(c,bucket,path,**kw):
        calls.append((bucket,path,kw));return 'https://signed.test/'+path
    monkeypatch.setattr(cards.storage_links,'signed_url',sign)
    return calls


def test_magic_beats_extension_and_signed_ttl(relay,monkeypatch):
    calls=signed(monkeypatch)
    got=create(upload(image(),'wrong.jpg','image/jpeg'),upload(image('JPEG'),'thumb.jpg','image/jpeg'),kind='image')
    row=relay.tables['dev_cards'][0]
    assert row['mime']=='image/png' and row['object_path'].endswith('original.png')
    assert row['device_id']==D1 and row['width']==20 and 'path' not in got['card']
    got=run(cards.card_get(row['id'],None))
    assert got['card']['has_file'] and got['card']['has_thumb']
    assert all(c[0]=='dev-desk' and c[2]['ttl']==900 for c in calls)
    relay.tick(30*86400)
    with pytest.raises(HTTPException) as e:run(cards.card_get(row['id'],None))
    assert e.value.status_code==404


@pytest.mark.parametrize('data,name,mime',[(b'<html>secret</html>','a.txt','text/plain'),
    (b'hello','a.html','text/plain'),(b'hello','a.env','text/html'),(b'\x89PNG\r\n\x1a\nbroken','a.png','image/png'),
    (b'\x00\xff','a.txt','text/plain'),(b'API_KEY=x','.env','text/plain')])
def test_refused_types(relay,data,name,mime):
    with pytest.raises(HTTPException) as e:create(upload(data,name,mime))
    assert e.value.status_code==415
    assert relay.tables['dev_cards']==[] and not relay.uploads


@pytest.mark.parametrize('data,thumb',[(b'x'*(11*1024*1024),None),
    (b'x'*(5*1024*1024+1),None),(image(),b'x'*(300*1024+1))], ids=['total','text','thumb'])
def test_size_caps(relay,data,thumb):
    with pytest.raises(HTTPException) as e:
        create(upload(data),upload(thumb) if thumb else None)
    assert e.value.status_code==413


def test_text_and_json_redacted_and_download_name(relay,monkeypatch):
    calls=signed(monkeypatch)
    create(upload(b'use sk-ant-'+b'a'*30,'notes.md','text/markdown'))
    create(upload(b'{"token":"short-secret"}','config.json','application/json'))
    payloads=[data for data,mime in relay.uploads.values()]
    assert payloads==[b'use [redacted:token]',b'{"token": "[redacted:secret]"}']
    assert calls[0][2]['download_as']=='notes.md'


def test_link_validation_and_local_preview(relay):
    for url in ['javascript:alert(1)','file:///secret','https://user:pw@host']:
        with pytest.raises(HTTPException) as e:create(kind='link',url=url)
        assert e.value.status_code==422
    card=create(kind='preview',url='http://localhost:5173')['card']
    assert card['url']=='http://localhost:5173' and not card['has_file']
    assert not relay.uploads


def test_failed_upload_is_cleaned_and_storage_delete_failure_keeps_retry_row(relay,monkeypatch):
    async def fail(*a):raise HTTPException(502,'storage unavailable')
    monkeypatch.setattr(cards,'_upload',fail)
    with pytest.raises(HTTPException):create(upload(b'hello'))
    assert not relay.tables['dev_cards']
    monkeypatch.setattr(cards,'_remove_objects',fail)
    with pytest.raises(HTTPException):create(upload(b'hello'))
    assert len(relay.tables['dev_cards'])==1
    assert store.parse(relay.tables['dev_cards'][0]['expires_at'])<=relay.stamp


def test_kai_only_signs_cards_on_returned_page(relay,monkeypatch):
    signed(monkeypatch)
    one=create(kind='link',url='https://example.com/one')['card']['id']
    two=create(kind='link',url='https://example.com/two')['card']['id']
    async def device(c):return None
    async def get(c,table,params):
        return [{'id':'m','meta':{'card':one}}]
    monkeypatch.setattr(dev_kai,'_kai_device',device)
    monkeypatch.setattr(dev_kai,'_sb_get',get)
    out=run(dev_kai.kai_thread(None,None))
    assert set(out['cards'])=={one} and two not in out['cards']
    assert run(cards.card_map(None,[{'meta':{'card':'not-a-uuid'}}]))=={}


def test_revoke_deletes_only_own_cards_and_storage(relay,monkeypatch):
    signed(monkeypatch)
    create(upload(b'one'));create(upload(b'two'),auth='Bearer two')
    run(dev_bridge.revoke_device(UUID(D1),None))
    assert {r['device_id'] for r in relay.tables['dev_cards']}=={D2}
    assert len(relay.uploads)==1 and next(iter(relay.uploads)).startswith(D2+'/')
    with pytest.raises(HTTPException) as e:create(kind='link',url='https://example.com')
    assert e.value.status_code==401


def test_real_multipart_route_and_total_body_cap(relay,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    signed(monkeypatch)
    app=FastAPI();app.include_router(cards.router)
    with TestClient(app) as client:
        response=client.post('/dev-bridge/cards',headers={'authorization':'Bearer one'},
            data={'meta':json.dumps({'kind':'image','title':'A picture','device_id':D2})},
            files={'file':('misnamed.jpg',image(),'image/jpeg'),
                   'thumb':('thumb.jpg',image('JPEG'),'image/jpeg')})
        assert response.status_code==200 and response.json()['card']['mime']=='image/png'
        assert relay.tables['dev_cards'][0]['device_id']==D1
        response=client.post('/dev-bridge/cards',headers={'authorization':'Bearer one'},
            data={'meta':json.dumps({'kind':'file'})},files={'file':('large.txt',b'x'*(11*1024*1024),'text/plain')})
        assert response.status_code==413


def test_revocation_during_upload_cleans_late_objects(relay,monkeypatch):
    async def upload_then_revoke(c,path,data,mime):
        relay.uploads[path]=(data,mime)
        # Revoke purges the row while the network upload is in flight.
        relay.tables['dev_cards']=[]
    monkeypatch.setattr(cards,'_upload',upload_then_revoke)
    with pytest.raises(HTTPException) as e:create(upload(b'hello'))
    assert e.value.status_code==409
    assert not relay.uploads


def test_card_redaction_runs_off_event_loop(relay, monkeypatch):
    import threading
    import dev_redact
    signed(monkeypatch)
    main_thread = threading.get_ident()
    seen = []
    original = dev_redact.text

    def checked(value):
        if 'card-private-value' in value:
            seen.append(threading.get_ident())
        return original(value)
    monkeypatch.setattr(dev_redact, 'text', checked)
    create(upload(b'token=card-private-value\n' * 200))
    assert seen and all(t != main_thread for t in seen)
    assert all(b'card-private-value' not in data for data, mime in relay.uploads.values())
