# coding=utf-8
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import
from __future__ import unicode_literals

from locale import bind_textdomain_codeset
from blueman.Functions import get_icon, dprint

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import Gio
import cgi
import blueman.bluez as Bluez
from blueman.Sdp import *
from blueman.Constants import *
from blueman.gui.Notification import Notification

from blueman.bluez.Agent import Agent

class BluezAgent(Agent):
    __agent_path = '/org/bluez/agent/blueman'

    def __init__(self, status_icon, time_func):
        super(BluezAgent, self).__init__(self.__agent_path, self._handle_method_call)

        self.status_icon = status_icon
        self.dialog = None
        self.n = None
        self.signal_id = None
        self.time_func = time_func

    def register_agent(self):
        dprint()
        self._register_object()
        Bluez.AgentManager().register_agent(self.__agent_path, "KeyboardDisplay", default=True)

    def unregister_agent(self):
        dprint()
        self._unregister_object()
        Bluez.AgentManager().unregister_agent(self.__agent_path)

    def _handle_method_call(self, connection, sender, agent_path, interface_name, method_name, parameters, invocation):

        if method_name == 'Release':
            self._on_release()
        elif method_name == 'RequestPinCode':
            self._on_request_pin_code(parameters, invocation)
        elif method_name == 'DisplayPinCode':
            self._on_display_pin_code(parameters, invocation)
        elif method_name == 'RequestPasskey':
            self._on_request_passkey(parameters, invocation)
        elif method_name == 'DisplayPasskey':
            self._on_display_passkey(parameters, invocation)
        elif method_name == 'RequestConfirmation':
            self._on_request_confirmation(parameters, invocation)
        elif method_name == 'RequestAuthorization':
            self._on_request_authorization(parameters, invocation)
        elif method_name == 'AuthorizeService':
            self._on_authorize_service(parameters, invocation)
        elif method_name == 'Cancel':
            self._on_cancel()
        else:
            dprint('Warning, unhandled method: %s' % method_name)

    def build_passkey_dialog(self, device_alias, dialog_msg, is_numeric):
        def on_insert_text(editable, new_text, new_text_length, position):
            if not new_text.isdigit():
                editable.stop_emission("insert-text")

        builder = Gtk.Builder()
        builder.add_from_file(UI_PATH + "/applet-passkey.ui")
        builder.set_translation_domain("blueman")
        bind_textdomain_codeset("blueman", "UTF-8")
        dialog = builder.get_object("dialog")

        dialog.props.icon_name = "blueman"
        dev_name = builder.get_object("device_name")
        dev_name.set_markup(device_alias)
        msg = builder.get_object("message")
        msg.set_text(dialog_msg)
        pin_entry = builder.get_object("pin_entry")
        show_input = builder.get_object("show_input_check")
        if (is_numeric):
            pin_entry.set_max_length(6)
            pin_entry.set_width_chars(6)
            pin_entry.connect("insert-text", on_insert_text)
            show_input.hide()
        else:
            pin_entry.set_max_length(16)
            pin_entry.set_width_chars(16)
            pin_entry.set_visibility(False)
        show_input.connect("toggled", lambda x: pin_entry.set_visibility(x.props.active))
        accept_button = builder.get_object("accept")
        pin_entry.connect("changed", lambda x: accept_button.set_sensitive(x.get_text() != ''))

        return (dialog, pin_entry)

    def get_device_alias(self, device_path):
        device = Bluez.Device(device_path)
        props = device.get_properties()
        address = props["Address"]
        name = props.get('Name', address)
        alias = address
        if name:
            alias = "<b>%s</b> (%s)" % (cgi.escape(name), address)
        return alias

    def ask_passkey(self, dialog_msg, notify_msg, is_numeric, notification, parameters, invocation):
        device_path = parameters.unpack()[0]

        def on_notification_close(n, action):
            if action != "closed":
                self.dialog.present()
            else:
                if self.dialog:
                    self.dialog.response(Gtk.ResponseType.REJECT)
                #self.applet.status_icon.set_blinking(False)

        def passkey_dialog_cb(dialog, response_id):
            if response_id == Gtk.ResponseType.ACCEPT:
                ret = pin_entry.get_text()
                if is_numeric:
                    ret = GLib.Variant('(u)', int(ret))
                invocation.return_value(GLib.Variant('(s)', (ret,)))
            else:
                invocation.return_dbus_error('org.bluez.Error.Rejected', 'Rejected')
            dialog.destroy()
            self.dialog = None

        alias = self.get_device_alias(device_path)
        notify_message = _("Pairing request for %s") % (alias)

        if self.dialog:
            dprint("Agent: Another dialog still active, cancelling")
            invocation.return_dbus_error('org.bluez.Error.Canceled', 'Canceled')

        self.dialog, pin_entry = self.build_passkey_dialog(alias, dialog_msg, is_numeric)
        if not self.dialog:
            dprint("Agent: Failed to build dialog")
            invocation.return_dbus_error('org.bluez.Error.Canceled', 'Canceled')

        if notification:
            Notification(_("Bluetooth Authentication"), notify_message, pixbuf=get_icon("blueman", 48),
                         status_icon=self.status_icon)
        #self.applet.status_icon.set_blinking(True)

        self.dialog.connect("response", passkey_dialog_cb)
        self.dialog.present()

    # Workaround BlueZ not calling the Cancel method, see #164
    def _on_device_property_changed(self, device, key, value, path):
        if (key == "Paired" and value) or (key == "Connected" and not value):
            device.disconnect_signal(self.signal_id)
            self._on_cancel()

    def _on_release(self):
        dprint("Agent.Release")
        self._on_cancel()
        self._unregister_object()

    def _on_cancel(self):
        dprint("Agent.Cancel")
        if self.dialog:
            self.dialog.response(Gtk.ResponseType.REJECT)
        try:
            self.n.close()
        except AttributeError:
            pass


    def _on_request_pin_code(self, parameters, invocation):
        dprint("Agent.RequestPinCode")
        dialog_msg = _("Enter PIN code for authentication:")
        notify_msg = _("Enter PIN code")
        self.ask_passkey(dialog_msg, notify_msg, False, True, parameters, invocation)
        if self.dialog:
            self.dialog.present_with_time(self.time_func())

    def _on_request_passkey(self, parameters, invocation):
        dprint("Agent.RequestPasskey")
        dialog_msg = _("Enter passkey for authentication:")
        notify_msg = _("Enter passkey")
        self.ask_passkey(dialog_msg, notify_msg, True, True, parameters, invocation)
        if self.dialog:
            self.dialog.present_with_time(self.time_func())

    def _on_display_passkey(self, parameters, invocation):
        device, passkey, entered = parameters.unpack()
        dprint('DisplayPasskey (%s, %d)' % (device, passkey))
        dev = Bluez.Device(device)
        self.signal_id = dev.connect_signal("property-changed", self._on_device_property_changed)

        notify_message = _("Pairing passkey for") + " %s: %s" % (self.get_device_alias(device), passkey)
        self.n = Notification("Bluetooth", notify_message, 0,
                              pixbuf=get_icon("blueman", 48), status_icon=self.status_icon)

    def _on_display_pin_code(self, parameters, invocation):
        device, pin_code = parameters.unpack()
        dprint('DisplayPinCode (%s, %s)' % (device, pin_code))
        dev = Bluez.Device(device)
        self.signal_id = dev.connect_signal("property-changed", self._on_device_property_changed)

        notify_message = _("Pairing PIN code for") + " %s: %s" % (self.get_device_alias(device), pin_code)
        self.n = Notification("Bluetooth", notify_message, 0,
                              pixbuf=get_icon("blueman", 48), status_icon=self.status_icon)

    def _on_request_confirmation(self, parameters, invocation):
        def on_confirm_action(n, action):
            if action == "confirm":
                invocation.return_value(GLib.Variant('()', ()))
            else:
                invocation.return_dbus_error('org.bluez.Error.Canceled', "User canceled pairing")

        params = parameters.unpack()
        if len(params) < 2:
            device_path = params[0]
            passkey = None
        else:
            device_path, passkey = params

        dprint("Agent.RequestConfirmation")
        alias = self.get_device_alias(device_path)
        notify_message = _("Pairing request for:") + "\n%s" % alias
        if passkey:
            notify_message += "\n" + _("Confirm value for authentication:") + " <b>%s</b>" % passkey
        actions = [["confirm", _("Confirm")], ["deny", _("Deny")]]

        self.n = Notification("Bluetooth", notify_message, 0, actions, on_confirm_action,
                              pixbuf=get_icon("blueman", 48), status_icon=self.status_icon)

    def _on_request_authorization(self, parameters, invocation):
        self._on_request_confirmation(parameters, invocation)

    def _on_authorize_service(self, parameters, invocation):
        def on_auth_action(n, action):
            dprint(action)

            #self.applet.status_icon.set_blinking(False)
            if action == "always":
                device = Bluez.Device(n._device)
                device.set("Trusted", True)
            if action == "always" or action == "accept":
                invocation.return_value(GLib.Variant('()', ()))
            else:
                invocation.return_dbus_error('org.bluez.Error.Rejected', 'Rejected')

            self.n = None

        device, uuid = parameters.unpack()

        dprint("Agent.Authorize")
        alias = self.get_device_alias(device)
        uuid16 = uuid128_to_uuid16(uuid)
        service = uuid16_to_name(uuid16)
        notify_message = (_("Authorization request for:") + "\n%s\n" + _("Service:") + " <b>%s</b>") % (alias, service)
        actions = [["always", _("Always accept")],
                   ["accept", _("Accept")],
                   ["deny", _("Deny")]]

        n = Notification(_("Bluetooth Authentication"), notify_message, 0,
                         actions, on_auth_action,
                         pixbuf=get_icon("blueman", 48), status_icon=self.status_icon)
        n._device = device
