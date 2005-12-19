# -*- Mode: Python; coding: iso-8859-1 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Stoqdrivers
## Copyright (C) 2005 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307,
## USA.
##
## Author(s):   Henrique Romano <henrique@async.com.br>
##
"""
stoqdrivers/devices/printers/perto/Pay2023.py:
    
    PertoPay 2023 driver implementation.
"""

from datetime import datetime

from serial import EIGHTBITS, PARITY_EVEN, STOPBITS_ONE
from zope.interface import implements

from stoqdrivers.devices.serialbase import SerialBase
from stoqdrivers.devices.printers.interface import (ICouponPrinter,
                                                    IChequePrinter)
from stoqdrivers.devices.printers.cheque import BaseChequePrinter, BankConfiguration
from stoqdrivers.constants import (TAX_IOF, TAX_ICMS, TAX_SUBSTITUTION,
                                   TAX_EXEMPTION, TAX_NONE)
from stoqdrivers.constants import (UNIT_WEIGHT, UNIT_METERS,
                                   UNIT_LITERS, UNIT_EMPTY)
from stoqdrivers.constants import MONEY_PM, CHEQUE_PM
from stoqdrivers.exceptions import (DriverError, PendingReduceZ,
                                    CommandParametersError, CommandError,
                                    ReadXError, OutofPaperError,
                                    CouponTotalizeError, PaymentAdditionError,
                                    CancelItemError, CouponOpenError,
                                    InvalidState, PendingReadX)
from stoqdrivers.devices.printers.capabilities import Capability
        
class Pay2023(SerialBase, BaseChequePrinter):
    implements(IChequePrinter, ICouponPrinter)

    printer_name = "Pertopay Fiscal 2023"

    CHEQUE_CONFIGFILE = 'perto.ini'

    CMD_PREFIX = '{'
    CMD_SUFFIX = '}'
    EOL_DELIMIT = CMD_SUFFIX

    CMD_READ_X = 'EmiteLeituraX'
    CMD_CANCEL_COUPON = 'CancelaCupom'
    CMD_CLOSE_TILL = 'EmiteReducaoZ'
    CMD_ADD_ITEM = 'VendeItem'
    CMD_COUPON_OPEN = 'AbreCupomFiscal'
    CMD_CANCEL_ITEM = 'CancelaItemFiscal'
    CMD_ADD_PAYMENT = 'PagaCupom'
    CMD_ADD_COUPON_DIFFERENCE = 'AcresceSubtotal'
    CMD_COUPON_CANCEL = 'CancelaCupom'
    CMD_COUPON_CLOSE = 'EncerraDocumento'
    CMD_GET_INTEGER_REGISTER_DATA = 'LeInteiro'
    CMD_GET_MONEY_REGISTER_DATA = 'LeMoeda'
    CMD_GET_LAST_ITEM_ID = 'ContadorDocUltimoItemVendido'
    CMD_GET_COUPON_TOTAL_VALUE = 'TotalDocLiquido'
    CMD_GET_COUPON_TOTAL_PAID_VALUE = 'TotalDocValorPago'
    CMD_PRINT_CHEQUE = 'ImprimeCheque'

    errors_dict = {7003: OutofPaperError,
                   7004: OutofPaperError,
                   8007: CouponTotalizeError,
                   8011: PaymentAdditionError,
                   8013: CouponTotalizeError,
                   8014: PaymentAdditionError,
                   8045: CancelItemError,
                   8068: PaymentAdditionError,
                   15009: PendingReduceZ,
                   11002: CommandParametersError,
                   11006: CommandError,
                   11007: InvalidState,
                   15007: PendingReadX,
                   15008: ReadXError,
                   15011: OutofPaperError}

    # FIXME: this part will be fixed at bug #2246
    taxcode_dict = {TAX_IOF: '0',
                    TAX_ICMS: '0',
                    TAX_SUBSTITUTION: '0',
                    TAX_EXEMPTION: '0',
                    TAX_NONE: '0'}

    unit_dict = {UNIT_WEIGHT: 'kg',
                 UNIT_METERS: 'm ',
                 UNIT_LITERS: 'lt',
                 UNIT_EMPTY: '  '}

    payment_methods = {MONEY_PM: '1',
                       CHEQUE_PM: '2'}

    #
    # Cheque elements position
    #

    def __init__(self, device, baudrate=115200, bytesize=EIGHTBITS,
                 parity=PARITY_EVEN, stopbits=STOPBITS_ONE):
        SerialBase.__init__(self, device, baudrate=baudrate, bytesize=bytesize,
                            parity=parity, stopbits=stopbits)
        BaseChequePrinter.__init__(self)

    #
    # Helper methods
    #

    def _send_command(self, command, **params):
        params = ["%s=%s" % (param, value) for param, value in params.items()]
        data = "%d;%s;%s;" % (self.get_next_command_id(), command,
                              " ".join(params))
        result = self.writeline("%s" % data)
        return result

    def send_command(self, command, **params):
        result = self._send_command(command, **params)
        self.handle_error(command, result)

    def handle_error(self, cmd, reply):
        """ Reply format:

            {CMD_ID;REPLY_CODE;REPLY_DESCRIPTION;CMD_SIZE}

        Where '{' is the reply prefix and '}' the suffix

        Note that the REPLY_DESCRIPTION field is composed by the following
        sections:

        NomeErro="A_STRING"
        Circunstancia="THE_REPLY_DESCRIPTION_ITSELF"
        """
        # removing REPLY_PREFIX and REPLY_SUFFIX
        reply = reply[1:-1]

        cmd_id, code, desc = reply.split(';')
        code = int(code)
        if code == 0:
            return
        # getting the "raw" reply description
        substr = "Circunstancia="
        desc_idx = desc.index(substr) + len(substr)
        desc = desc[desc_idx:]
        try:
            exception = Pay2023.errors_dict[code]
        except KeyError:
            raise DriverError("%d: %s" % (code, desc))
        raise exception(desc)

    def get_next_command_id(self):
        # I don't want to work with (and manage!) many commands at the same
        # time, so returning always 0 I can avoid this (all the same ids,
        # all the fuck*** time)
        return 0

    def get_last_item_id(self):
        name = "\"%s\"" % Pay2023.CMD_GET_LAST_ITEM_ID
        result = self._send_command(Pay2023.CMD_GET_INTEGER_REGISTER_DATA,
                                    NomeInteiro=name)
        result = result[:-1]
        substr = "ValorInteiro"
        index = result.index(substr) + len(substr) + 1
        value = int(result[index:])
        return value

    def get_money_register_data(self, data_name):
        result = self._send_command(Pay2023.CMD_GET_MONEY_REGISTER_DATA,
                                    NomeDadoMonetario="\"%s\"" % name)
        result = result[:-1]
        substr = "ValorMoeda"
        index = result.index(substr) + len(substr) + 1
        return self.parse_value(result[index:])

    def get_coupon_total_value(self):
        name = Pay2023.CMD_GET_COUPON_TOTAL_VALUE
        return self.get_money_register_data(name)

    def get_coupon_remainder_value(self):
        name = Pay2023.CMD_GET_COUPON_TOTAL_PAID_VALUE
        value =  self.get_money_register_data(name)
        result = self.get_coupon_total_value() - value
        if result < 0.0:
            result = 0.0
        return result

    def format_value(self, value):
        """ This method receives a float value and format it to the string
        format accepted by the FISCnet protocol.
        """
        return ("%.04f" % value).replace('.', ',')

    def parse_value(self, value):
        """ This method receives a string value (representing the float
        format used in the FISCnet protocol) and convert it to the
        Python's float format.
        """
        if ',' in value:
            value = value.replace(',', '.')
        return float(value)

    #
    # ICouponPrinter implementation
    #


    def coupon_open(self, customer, address, document):
        try:
            self.send_command(Pay2023.CMD_COUPON_OPEN,
                              EnderecoConsumidor="\"%s\"" % address[:80],
                              IdConsumidor="\"%s\"" % document[:29],
                              NomeConsumidor="\"%s\"" % customer[:30])
        except InvalidState:
            raise CouponOpenError("Coupon already opened.")

    def coupon_add_item(self, code, quantity, price, unit, description, taxcode,
                        discount, surcharge):        
        # FIXME: these magic numbers will be remove when the bug #2176 is fixed
        self.send_command(Pay2023.CMD_ADD_ITEM,
                          CodAliquota=Pay2023.taxcode_dict[taxcode],
                          CodProduto="\"%s\"" % code[:48],
                          NomeProduto="\"%s\"" % description[:200],
                          Unidade="\"%02s\"" % Pay2023.unit_dict[unit],
                          PrecoUnitario=self.format_value(price),
                          Quantidade="%.03f" % quantity)
        return self.get_last_item_id()

    def coupon_cancel_item(self, item_id):
        self.send_command(Pay2023.CMD_CANCEL_ITEM, NumItem=item_id)

    def coupon_cancel(self):
        self.send_command(Pay2023.CMD_COUPON_CANCEL)

    def coupon_totalize(self, discount, surcharge, taxcode):
        # The FISCnet protocol (the protocol used in this printer model)
        # doesn't have a command to totalize the coupon, so we just get
        # the discount/surcharge values and applied to the coupon.
        value = discount and (discount * -1) or surcharge
        if value:
            self.send_command(Pay2023.CMD_ADD_COUPON_DIFFERENCE, Cancelar='f',
                              ValorPercentual="%.02f" % value)
        return self.get_coupon_total_value()

    def coupon_add_payment(self, payment_method, value, description=''):
        pm = Pay2023.payment_methods[payment_method]
        self.send_command(Pay2023.CMD_ADD_PAYMENT,
                          CodMeioPagamento=pm, Valor=self.format_value(value),
                          TextoAdicional="\"%s\"" % description[:80])
        return self.get_coupon_remainder_value()
        
    def coupon_close(self, message=''):
        # FIXME: these magic numbers will be remove when the bug #2176 is fixed
        self.send_command(Pay2023.CMD_COUPON_CLOSE,
                          TextoPromocional="\"%s\"" % message[:492])

    def summarize(self):
        self.send_command(Pay2023.CMD_READ_X)

    def close_till(self):
        self.send_command(Pay2023.CMD_CLOSE_TILL)

    #
    # IChequePrinter implementation
    #

    def print_cheque(self, bank, value, thirdparty, city, date=datetime.now()):
        if not isinstance(bank, BankConfiguration):
            raise TypeError("bank parameter must be BankConfiguration instance")

        data = dict(HPosAno=bank.get_x_coordinate("year"),
                    HPosCidade=bank.get_x_coordinate("city"),
                    HPosDia=bank.get_x_coordinate("day"),
                    HPosExtensoLinha1=bank.get_x_coordinate("legal_amount"),
                    HPosExtensoLinha2=bank.get_x_coordinate("legal_amount2"),
                    HPosFavorecido=bank.get_x_coordinate("thirdparty"),
                    HPosMes=bank.get_x_coordinate("month"),
                    HPosValor=bank.get_x_coordinate("value"),
                    VPosCidade=bank.get_y_coordinate("city"),
                    VPosExtensoLinha1=bank.get_y_coordinate("legal_amount"),
                    VPosExtensoLinha2=bank.get_y_coordinate("legal_amount2"),
                    VPosFavorecido=bank.get_y_coordinate("thirdparty"),
                    VPosValor=bank.get_y_coordinate("value"))

        self.send_command(Pay2023.CMD_PRINT_CHEQUE, Cidade="\"%s\"" % city[:27],
                          Data=date.strftime("#%d/%m/%Y#"),
                          Favorecido="\"%s\"" % thirdparty[:45],
                          Valor=self.format_value(value), **data)

    def get_capabilities(self):
        return dict(item_code=Capability(max_len=48),
                    item_id=Capability(max_size=32767),
                    items_quantity=Capability(digits=14, decimals=4),
                    item_price=Capability(digits=14, decimals=4),
                    item_description=Capability(max_len=200),
                    payment_value=Capability(digits=14, decimals=4),
                    promotional_message=Capability(max_len=492),
                    payment_description=Capability(max_len=80),
                    customer_name=Capability(max_len=30),
                    customer_id=Capability(max_len=29),
                    customer_address=Capability(max_len=80),
                    cheque_thirdparty=Capability(max_len=45),
                    cheque_value=Capability(digits=14, decimals=4),
                    cheque_city=Capability(max_len=27))