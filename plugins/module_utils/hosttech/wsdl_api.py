# -*- coding: utf-8 -*-
#
# Copyright (c) 2017-2021 Felix Fontein
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


from ansible.module_utils.six import raise_from
from ansible.module_utils._text import to_native

from ansible_collections.community.dns.plugins.module_utils.record import (
    DNSRecord,
)

from ansible_collections.community.dns.plugins.module_utils.wsdl import (
    WSDLError,
    WSDLNetworkError,
    Composer,
)

from ansible_collections.community.dns.plugins.module_utils.zone import (
    DNSZone,
    DNSZoneWithRecords,
)

from ansible_collections.community.dns.plugins.module_utils.zone_record_api import (
    DNSAPIError,
    DNSAPIAuthenticationError,
    ZoneRecordAPI,
)


def _create_record_from_encoding(source, type=None):
    result = DNSRecord()
    result.id = source['id']
    result.type = source.get('type', type)
    result.prefix = source.get('prefix')
    result.ttl = int(source['ttl']) if source['ttl'] is not None else None
    if result.type in ('PTR', 'MX'):
        result.target = '{0} {1}'.format(source.get('priority'), source.get('target'))
    else:
        result.target = source.get('target')
    return result


def _create_zone_from_encoding(source):
    zone = DNSZone(source['name'])
    zone.id = source['id']
    # zone.email = source.get('email')
    # zone.ttl = int(source['ttl'])
    # zone.nameserver = source['nameserver']
    # zone.serial = source['serial']
    # zone.template = source.get('template')
    return DNSZoneWithRecords(zone, [_create_record_from_encoding(record) for record in source['records']])


def _encode_record(record, include_id=False):
    result = {
        'type': record.type,
        'prefix': record.prefix,
        'target': record.target,
        'ttl': record.ttl,
    }
    if record.type in ('PTR', 'MX'):
        try:
            priority, target = record.target.split(' ', 1)
            result['priority'] = int(priority)
            result['target'] = target
        except Exception as e:
            raise DNSAPIError(
                'Cannot split {0} record "{1}" into integer priority and target: {2}'.format(
                    record.type, record.target, e))
    else:
        result['priority'] = None
    if include_id:
        result['id'] = record.id
    return result


def _encode_zone(zone):
    return {
        'id': zone.id,
        'name': zone.name,
        # 'email': zone.email,
        # 'ttl': zone.ttl,
        # 'nameserver': zone.nameserver,
        # 'serial': zone.serial,
        # 'template': zone.template,
        'records': [_encode_record(record, include_id=True) for record in zone.records],
    }


class HostTechWSDLAPI(ZoneRecordAPI):
    def __init__(self, username, password, api='https://ns1.hosttech.eu/public/api', debug=False):
        """
        Create a new HostTech API instance with given username and password.
        """
        self._api = api
        self._namespaces = {
            'ns1': 'https://ns1.hosttech.eu/soap',
        }
        self._username = username
        self._password = password
        self._debug = debug

    def _prepare(self):
        command = Composer(self._api, self._namespaces)
        command.add_auth(self._username, self._password)
        return command

    def _announce(self, msg):
        if self._debug:
            pass
            # q.q('{0} {1} {2}'.format('=' * 4, msg, '=' * 40))

    def _execute(self, command, result_name, acceptable_types):
        if self._debug:
            pass
            # q.q('Request: {0}'.format(command))
        try:
            result = command.execute(debug=self._debug)
        except WSDLError as e:
            if e.error_code == '998':
                raise DNSAPIAuthenticationError('Error on authentication ({0})'.format(e.error_message))
            raise
        res = result.get_result(result_name)
        if isinstance(res, acceptable_types):
            if self._debug:
                pass
                # q.q('Extracted result: {0} (type {1})'.format(res, type(res)))
            return res
        if self._debug:
            pass
            # q.q('Result: {0}; extracted type {1}'.format(result, type(res)))
        raise DNSAPIError('Result has unexpected type {0} (expecting {1})!'.format(type(res), acceptable_types))

    def get_zone_with_records_by_name(self, name):
        """
        Given a zone name, return the zone contents with records if found.

        @param name: The zone name (string)
        @return The zone information with records (DNSZoneWithRecords), or None if not found
        """
        self._announce('get zone')
        command = self._prepare()
        command.add_simple_command('getZone', sZoneName=name)
        try:
            return _create_zone_from_encoding(self._execute(command, 'getZoneResponse', dict))
        except WSDLError as exc:
            if exc.error_origin == 'server' and exc.error_message == 'zone not found':
                return None
            raise_from(DNSAPIError('Error while getting zone: {0}'.format(to_native(exc))), exc)
        except WSDLNetworkError as exc:
            raise_from(DNSAPIError('Network error while getting zone: {0}'.format(to_native(exc))), exc)

    def get_zone_with_records_by_id(self, id):
        """
        Given a zone ID, return the zone contents with records if found.

        @param id: The zone ID
        @return The zone information with records (DNSZoneWithRecords), or None if not found
        """
        return self.get_zone_with_records_by_name(str(id))

    def get_zone_by_name(self, name):
        """
        Given a zone name, return the zone contents if found.

        @param name: The zone name (string)
        @return The zone information (DNSZone), or None if not found
        """
        zone = self.get_zone_with_records_by_name(name)
        return zone.zone if zone else None

    def get_zone_by_id(self, id):
        """
        Given a zone ID, return the zone contents if found.

        @param id: The zone ID
        @return The zone information (DNSZone), or None if not found
        """
        zone = self.get_zone_with_records_by_id(id)
        return zone.zone if zone else None

    def add_record(self, zone_id, record):
        """
        Adds a new record to an existing zone.

        @param zone_id: The zone ID
        @param record: The DNS record (DNSRecord)
        @return The created DNS record (DNSRecord)
        """
        self._announce('add record')
        command = self._prepare()
        command.add_simple_command('addRecord', search=str(zone_id), recorddata=_encode_record(record, include_id=False))
        try:
            return _create_record_from_encoding(self._execute(command, 'addRecordResponse', dict))
        except WSDLError as exc:
            raise_from(DNSAPIError('Error while adding record: {0}'.format(to_native(exc))), exc)
        except WSDLNetworkError as exc:
            raise_from(DNSAPIError('Network error while adding record: {0}'.format(to_native(exc))), exc)

    def update_record(self, zone_id, record):
        """
        Update a record.

        @param zone_id: The zone ID
        @param record: The DNS record (DNSRecord)
        @return The DNS record (DNSRecord)
        """
        if record.id is None:
            raise DNSAPIError('Need record ID to update record!')
        self._announce('update record')
        command = self._prepare()
        command.add_simple_command('updateRecord', recordId=record.id, recorddata=_encode_record(record, include_id=False))
        try:
            return _create_record_from_encoding(self._execute(command, 'updateRecordResponse', dict))
        except WSDLError as exc:
            raise_from(DNSAPIError('Error while updating record: {0}'.format(to_native(exc))), exc)
        except WSDLNetworkError as exc:
            raise_from(DNSAPIError('Network error while updating record: {0}'.format(to_native(exc))), exc)

    def delete_record(self, zone_id, record):
        """
        Delete a record.

        @param zone_id: The zone ID
        @param record: The DNS record (DNSRecord)
        @return True in case of success (boolean)
        """
        if record.id is None:
            raise DNSAPIError('Need record ID to delete record!')
        self._announce('delete record')
        command = self._prepare()
        command.add_simple_command('deleteRecord', recordId=record.id)
        try:
            return self._execute(command, 'deleteRecordResponse', bool)
        except WSDLError as exc:
            raise_from(DNSAPIError('Error while deleting record: {0}'.format(to_native(exc))), exc)
        except WSDLNetworkError as exc:
            raise_from(DNSAPIError('Network error while deleting record: {0}'.format(to_native(exc))), exc)
