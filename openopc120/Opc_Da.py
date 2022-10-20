import string

import logging
import os
from dataclasses import dataclass
from enum import Enum
from collections import namedtuple

from openopc120.exceptions import OPCError

from openopc120.pythoncom_datatypes import VtType
import pythoncom
logger = logging.getLogger(__name__)

import pywintypes

# Win32 only modules not needed for 'open' protocol mode
if os.name == 'nt':
    try:
        # TODO: chose bewtween pywin pythoncom and wind32 but do not use both
        import pythoncom
        import win32com.client
        import win32com.server.util
        import win32event
        import SystemHealth as SystemHealth

        # Win32 variant types
        pywintypes.datetime = pywintypes.TimeType

        # Allow gencache to create the cached wrapper objects
        win32com.client.gencache.is_readonly = False

        # Under p2exe the call in gencache to __init__() does not happen
        # so we use Rebuild() to force the creation of the gen_py folder
        win32com.client.gencache.Rebuild(verbose=0)

    # So we can work on Windows in "open" protocol mode without the need for the win32com modules
    except ImportError as e:
        print(e)
        win32com_found = False
    else:
        win32com_found = True
else:
    win32com_found = False

ACCESS_RIGHTS = (0, 'Read', 'Write', 'Read/Write')
OPC_QUALITY = ('Bad', 'Uncertain', 'Unknown', 'Good')


@dataclass
class TagPropertyItem:
    data_type = None
    value = None
    description = None
    property_id = None

    def get_default_tuple(self):
        return self.property_id, self.description, self.value


@dataclass
class TagProperty:
    data_type = None
    value = None
    quality = None
    timestamp = None
    access_rights = None
    server_scan_rate = None
    eu_type = None
    eu_info = None
    description = None

    def get_default_tuple(self):
        return self.property_id, self.description, self.value


tag_property_fields = [
    'DataType', 'Value', 'Quality', 'Timestamp', 'AccessRights', 'ServerScanRate', 'ItemEUType', 'ItemEUInfo',
    'Description']
TagPropertyNames = namedtuple('TagProperty', tag_property_fields, defaults=[None] * len(tag_property_fields))


class TagPropertyId(Enum):
    ItemCanonicalDatatype = 1
    ItemValue = 2
    ItemQuality = 3
    ItemTimeStamp = 4
    ItemAccessRights = 5
    ServerScanRate = 6
    ItemEUType = 7
    ItemEUInfo = 8
    ItemDescription = 101

    @classmethod
    def all_ids(cls):
        return [property_id.value for property_id in cls]

    @classmethod
    def all_names(cls):
        return [property_id.name for property_id in cls]


class OpcCom:
    def __init__(self, opc_class: str):
        # TODO: Get browser type (hierarchical etc)
        self.server: string = None
        self.host: string = 'localhost'
        self.groups = None
        self.opc_class = opc_class
        self.client_name = None
        self.server_name = None
        self.server_state = None
        self.major_version = None
        self.minor_version = None
        self.build_number = None
        self.start_time = None
        self.current_time = None
        self.vendor_info = None
        self.opc_client = None
        self.initialize_client(opc_class)

    def initialize_client(self, opc_class):
        try:
            print(f"Initialize OPC DA client: '{opc_class}'")
            pythoncom.CoInitialize()
            self.opc_client = win32com.client.gencache.EnsureDispatch(opc_class, 0)
        except pythoncom.com_error as err:
            # TODO: potential memory leak, destroy pythoncom
            logger.exception(exc_info=True)
            logger.exception('Error in initialize client')
            pythoncom.CoUninitialize()
            raise OPCError(f'Dispatch: {err}')

    def connect(self, host: str, server: str):
        self.server = server
        self.host = host
        try:
            print(f"Connectiong OPC Client Com interface: {self.server}, {self.host}")
            self.opc_client.Connect(self.server, self.host)
        except Exception as e:
            print(f"Error Connecting OPC Client Com interface: {self.server}, {self.host}")

            logger.exception('Error connecting OPC Client', exc_info=True)
            pass
        self.groups = self.opc_client.OPCGroups
        self.client_name = self.opc_client.ClientName
        self.server_name = self.opc_client.ServerName
        self.server_state = self.opc_client.ServerState
        self.major_version = self.opc_client.MajorVersion
        self.minor_version = self.opc_client.MinorVersion
        self.build_number = self.opc_client.BuildNumber
        self.start_time = self.opc_client.StartTime
        self.current_time = self.opc_client.CurrentTime
        self.vendor_info = self.opc_client.VendorInfo

        # for key in dir(self.opc_client):
        #     method = getattr(self.opc_client, key)
        #     print(key)
        #     if str(type(method)) == "<type 'instance'>":
        #         print(key)
        #         for sub_method in dir(method):
        #             if not sub_method.startswith("_") and not "clsid" in sub_method.lower():
        #                 print("\t" + sub_method)
        #     else:
        #         print("\t", method)

    def create_browser(self):
        return self.opc_client.CreateBrowser()

    def disconnect(self):
        self.opc_client.Disconnect()

    def server_name(self):
        return self.opc_client.ServerName

    def get_opc_servers(self, opc_host):
        return self.opc_client.GetOPCServers(opc_host)

    def get_available_properties(self, tag):
        (count, property_id, descriptions, datatypes) = list(self.opc_client.QueryAvailableProperties(tag))
        return count, property_id, descriptions, datatypes

    def _property_value_conversion(self, description, input_value):
        value = input_value

        if description == 'Item Canonical DataType':
            value = VtType(value).name
        if description == 'Item Timestamp':
            value = str(value)
        if description == 'Item Access Rights':
            value = ACCESS_RIGHTS[value]
        if description == 'Item Quality':
            if value > 3:
                value = 3
            value = OPC_QUALITY[value]

        return value

    def get_tag_properties(self, tag, property_ids=[]):
        # TODO: Find out if it makes any difference to request selected properties (so far there is no benefit)
        property_ids_filter = property_ids

        count, property_ids, descriptions, datatypes = self.get_available_properties(tag)
        available_properies_by_id = {}
        for result in zip(property_ids, descriptions, datatypes):
            available_properies_by_id[result[0]] = {
                'property_id': result[0],
                'description': result[1],
                'data_type': result[2]
            }

        property_ids_cleaned = [p for p in property_ids if p > 0]
        if property_ids_filter:
            property_ids_cleaned = [p for p in property_ids if p in property_ids_filter]
            # I assume this is nevessary due to 1 indexed arrays in windows
            property_ids_cleaned.insert(0, 0)

        item_properties_values, errors = self.opc_client.GetItemProperties(tag, len(property_ids_cleaned) - 1,
                                                                           property_ids_cleaned)

        if property_ids_filter:
            property_ids_cleaned.remove(0)

        # Create tag property item in a readable form. One item is one propeterty, there are many properties for one tag
        properties_by_description = {}

        if not property_ids_filter:
            # Add first property for compatibility
            tag_property_item = TagPropertyItem()
            tag_property_item.property_id = 0
            tag_property_item.description = 'Item ID (virtual property)'
            tag_property_item.value = tag

            properties_by_description[tag_property_item.description] = tag_property_item
            item_properties_values = list(item_properties_values)
            item_properties_values.insert(0, 0)

        for property_result in zip(property_ids_cleaned, item_properties_values):
            tag_property_item = TagPropertyItem()
            property = available_properies_by_id[property_result[0]]
            tag_property_item.data_type = VtType(property['data_type']).name
            tag_property_item.property_id = property['property_id']
            tag_property_item.description = property['description']
            tag_property_item.value = self._property_value_conversion(tag_property_item.description, property_result[1])

            properties_by_description[tag_property_item.description] = tag_property_item

        return [tag_property.get_default_tuple() for tag_property in properties_by_description.values()], errors

    def get_error_string(self, error_id: int):
        return self.opc_client.GetErrorString(error_id)

    def __str__(self):
        return f"OPCCom Object: {self.host} {self.server} {self.minor_version}.{self.major_version}"

    @staticmethod
    def get_quality_string(quality_bits):
        """Convert OPC quality bits to a descriptive string"""

        quality = (quality_bits >> 6) & 3
        return OPC_QUALITY[quality]

    @staticmethod
    def get_vt_type(datatype_number: int):
        return VtType(datatype_number).name
