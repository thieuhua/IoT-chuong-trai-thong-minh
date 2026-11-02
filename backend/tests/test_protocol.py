from __future__ import annotations

import json

import pytest

from iot_core import protocol as p


def test_topics():
    assert p.device_topic('esp32-1234', 'cmd') == 'iot/v1/esp32-1234/cmd'
    assert p.provision_request_topic('1234') == 'iot/v1/provision/1234/request'
    assert p.provision_response_topic('1234') == 'iot/v1/provision/1234/response'
    assert p.parse_topic(p.provision_request_topic('1234')) == p.TopicInfo(p.PROVISION_REQUEST, '1234')
    for leaf in p.DEVICE_LEAVES:
        assert p.parse_topic(p.device_topic('esp32-1234', leaf)) == p.TopicInfo(leaf, 'esp32-1234')
    for topic in ('iot/v1/provision/status', 'iot/v1/x/status', 'iot/v1/abc/cmd',
                  'iot/v1/provision/G123/request', 'other/abc/status'):
        assert p.parse_topic(topic) is None
    assert p.default_device_id('1234') == 'esp32-1234'
    assert not p.is_valid_device_id('provision')
    assert not p.is_valid_device_id('ABC')


def test_envelope_roundtrip():
    envelope = p.command('read', {'sensor': 'room'})
    assert p.Envelope.decode(envelope.encode(), p.CMD) == envelope
    assert p.provision_response('approved', 'esp32-1234').data == {'status': 'approved', 'device_id': 'esp32-1234'}
    assert p.Envelope.decode(p.Envelope(p.TELEMETRY, ts=None).encode()).ts is None


@pytest.mark.parametrize('payload', [b'', b'\xff', b'[]', b'{}', b'x' * 4097])
def test_bad_payload(payload):
    with pytest.raises(p.ProtocolError):
        p.Envelope.decode(payload)


@pytest.mark.parametrize('field,value', [('v', 2), ('id', ''), ('type', 1), ('data', []), ('ts', True), ('ts', 'now')])
def test_bad_envelope_fields(field, value):
    data = json.loads(p.Envelope(p.STATUS).encode())
    data[field] = value
    with pytest.raises(p.ProtocolError):
        p.Envelope.decode(json.dumps(data).encode())


def test_type_and_size():
    with pytest.raises(p.ProtocolError):
        p.Envelope.decode(p.Envelope(p.STATUS).encode(), p.META)
    with pytest.raises(p.ProtocolError):
        p.Envelope(p.META, {'huge': 'x' * 4096}).encode()
