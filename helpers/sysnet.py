"""
System utils for network administration.
"""
import socket
import struct

from helpers import remote
from helpers.error import Error

__author__ = 'Tempesta Technologies, Inc.'
__copyright__ = 'Copyright (C) 2019 Tempesta Technologies, Inc.'
__license__ = 'GPL2'


def ip_str_to_number(ip_addr):
    """ Convert ip to number """
    packed = socket.inet_aton(ip_addr)
    return struct.unpack("!L", packed)[0]


def ip_number_to_str(ip_addr):
    """ Convert ip in numeric form to string """
    packed = struct.pack("!L", ip_addr)
    return socket.inet_ntoa(packed)


def create_interface(iface_id, base_iface_name, base_ip):
    """ Create interface alias for listeners on nginx machine """
    base_ip_addr = ip_str_to_number(base_ip)
    iface_ip_addr = base_ip_addr + iface_id
    iface_ip = ip_number_to_str(iface_ip_addr)

    iface = "%s:%i" % (base_iface_name, iface_id)

    command = "LANG=C ip address add %s/24 dev %s label %s" % \
        (iface_ip, base_iface_name, iface)
    try:
        tf_cfg.dbg(3, "Adding ip %s" % iface_ip)
        remote.server.run_cmd(command)
    except:
        tf_cfg.dbg(3, "Interface alias already added")

    return (iface, iface_ip)


def remove_interface(interface_name, iface_ip):
    """ Remove interface """
    template = "LANG=C ip address del %s/24 dev %s"
    try:
        tf_cfg.dbg(3, "Removing ip %s" % iface_ip)
        remote.server.run_cmd(template % (iface_ip, interface_name))
    except:
        tf_cfg.dbg(3, "Interface alias already removed")


def create_interfaces(base_interface_name, base_interface_ip, number_of_ip):
    """ Create specified amount of interface aliases """
    ips = []
    for i in range(number_of_ip):
        (_, ip) = create_interface(i, base_interface_name, base_interface_ip)
        ips.append(ip)
    return ips


def remove_interfaces(base_interface_name, ips):
    """ Remove previously created interfaces """
    for ip in ips:
        remove_interface(base_interface_name, ip)


def route_dst_ip(node, ip):
    """ Determine outgoing interface for the IP. """
    command = "LANG=C ip route get to %s | grep -o 'dev [a-zA-Z0-9_-]*'" % ip
    try:
        res, _ = node.run_cmd(command)
        return res.split()[1]
    except Error as err:
        raise Error("Can not determine outgoing device for %s: %s"
                    % (ip, err))


def get_mtu(node, dev):
    command = "LANG=C ip addr show %s|grep -o 'mtu [0-9]*'" % dev
    try:
        res, _ = node.run_cmd(command)
        return int(res.split()[1])
    except Error as err:
        raise Error("Can not determine MTU for device %s: %s" % (ip, err))


def change_mtu(node, dev, mtu):
    """ Change the device MTU and return previous MTU. """
    prev_mtu = get_mtu(node, dev)
    command = "LANG=C ip link set %s mtu %d" % (dev, mtu)
    try:
        node.run_cmd(command)
    except Error as err:
        raise Error("Can not determine outgoing device for %s: %s"
                    % (ip, err))
    if mtu != get_mtu(node, dev):
        raise Error("Cannot set MTU %d for device %s" % (mtu, dev))
    return prev_mtu

