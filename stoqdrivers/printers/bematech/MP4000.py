# -*- coding: utf-8 -*-
"""
Created on Thu Sep  6 17:12:46 2012

 @author: truiz
"""

import datetime
import logging
import re

from stoqdrivers.exceptions import AlmostOutofPaper
from stoqdrivers.printers.bematech.MP25 import (
    CMD_COUPON_OPEN, CMD_COUPON_TOTALIZE, CMD_GET_COUPON_NUMBER, CMD_STATUS,
    CMD_READ_REGISTER, CMD_READ_TOTALIZERS, CMD_PROGRAM_PAYMENT_METHOD,
    CMD_ADD_TAX, MP25, RETRIES_BEFORE_TIMEOUT, CancelItemError, Capability,
    CommandError, CouponNotOpenError, CouponOpenError, CouponTotalizeError,
    Decimal, DriverError, HardwareFailure, ItemAdditionError, OutofPaperError,
    PaymentAdditionError, PrinterError, PrinterOfflineError, TaxType, UnitType,
    bcd2dec, bcd2hex, currency, stoqdrivers_gettext, struct)

log = logging.getLogger('stoqdrivers.bematech.MP4000')
_ = stoqdrivers_gettext

CMD_ADD_ITEM = 0x3e47  # this is different from mp25
# CMD_ADD_ITEM = 0x09  # Simple add item
CMD_FISCAL_APP = 0x3e40  # set fiscal app name
CMD_PAPER_SENSOR = 0x3e3d  # set fiscal app name
CMD_Z_TIME_LIMIT = 90
CMD_TD_ECV = 17
CMD_LAST_Z = 0x3e37
CMD_TRANSACTIONS = 0x3e4737  # get transactions from a given period
CMD_ADD_REFUND = 0x3e4733  # article return
CMD_CREDIT_NOTE_OPEN = 89
ECK = 0x03
CMD_READ_TAXCODES = 0x1a
CMD_PROGRAM_MULTI_PAYMENT_METHOD = 0x49


class MP4000Registers(object):
    TOTAL = 3
    TOTAL_CANCELATIONS = 4
    TOTAL_DISCOUNT = 5
    COO = 6
    GNF = 7
    NUMBER_REDUCTIONS_Z = 9
    CRO = 10
    LAST_ITEM_ID = 12
    NUMBER_TILL = 14
    NUMBER_STORE = 15
    CURRENCY = 16
    FISCAL_FLAGS = 17
    EMISSION_DATE = 23
    LAST_Z_DATE = 26
    TRUNC_FLAG = 28
    SERIAL = 40
    FIRMWARE = 41
    RIF = 42
    NIT = 44
    OPERATION_TIME = 45
    PAYMENT_METHODS = 49
    CCF = 55
    PRINTER_INFO = 60
    GERENCIAL_TIME = 71  # Seconds that remains to close gerencial report
    DAY_TOTAL = 77  # Ventas brutas diarias
    PRINTER_SENSORS = 254
    CNC = 255  # Credit notes counter

    # (size, bcd)
    formats = {
        TOTAL: ('9s', True),
        TOTAL_CANCELATIONS: ('7s', True),
        TOTAL_DISCOUNT: ('7s', True),
        COO: ('3s', True),
        GNF: ('3s', True),
        NUMBER_REDUCTIONS_Z: ('2s', True),
        CRO: ('2s', True),
        LAST_ITEM_ID: ('2s', True),
        NUMBER_TILL: ('2s', True),
        NUMBER_STORE: ('2s', True),
        FISCAL_FLAGS: ('1s', False),
        EMISSION_DATE: ('6s', False),
        LAST_Z_DATE: ('6s', False),
        TRUNC_FLAG: ('1s', False),
        PAYMENT_METHODS: ('620s', False),
        SERIAL: ('20s', False),
        FIRMWARE: ('3s', True),
        CCF: ('3s', True),
        GERENCIAL_TIME: ('4s', True),
        RIF: ('20s', False),
        NIT: ('20s', False),
        PRINTER_INFO: ('42s', False),
        CURRENCY: ('2s', False),
        PRINTER_SENSORS: ('B', False),
        OPERATION_TIME: ('2s', True),
        DAY_TOTAL: ('7s', True),
        CNC: ('3s', True),
    }


class MP4000(MP25):
    model_name = "Bematech MP4000 TH FI"
    CMD_PROTO = 0x1b
    reply_format = '<B%sBB'
    status_size = 2
    registers = MP4000Registers

    def coupon_open(self):
        """ This needs to be called before anything else """
        self._send_command(CMD_COUPON_OPEN,
                           "%-41s%-18s%-133s" % (self._customer_name,
                                                 self._customer_document,
                                                 self._customer_address))

    def credit_note_open(self, coo):
        """ This needs to be called before anything else """
        # print "%-41s%-15s%-18s%-12s%-6s" % (self._customer_name,
        # self.get_serial(),
        # self._customer_document,
        # datetime.datetime.now().strftime('%d%m%y%H%M%S'),
        # '00768')
        self._send_command(CMD_CREDIT_NOTE_OPEN,
                           "%-41s%-15s%-18s%-12s%06d" %
                           (self._customer_name, self.get_serial(),
                            self._customer_document,
                            datetime.date.today().strftime('%d%m%y%H%M%S'),
                            coo or 0))

    def coupon_add_item(self, code, description, price, taxcode,
                        quantity=Decimal("1.0"), unit=UnitType.EMPTY,
                        discount=Decimal("0.0"), markup=Decimal("0.0"),
                        unit_desc="", refund=False):
        """ The ECF must be configured to round instead to truncate.
        When truncating, the value may be lower then the one calculated
        by stoq. In this case, the payments added will be higher than the ECF
        expects, and a cents change will be printed.
        """
        if unit == UnitType.CUSTOM:
            unit = unit_desc
        else:
            unit = self._consts.get_value(unit)

        data = ("%02s"     # taxcode       (2)
                "%011d"    # value       (8+3) int+dec
                "%07d"     # quantity    (4+3) int+dec
                "%010d"    # discount    (8+2) int+dec
                "%010d"    # increment   (8+2) int+dec
                "%02d"     # fixed 01      (2)
                "%020d"    # zero padding (20)
                "%2s"      # unit          (2)
                "%-s\0"    # code         (49) max
                "%-s\0"    # description (201) max
                % (taxcode[:2],
                   price * Decimal("1e3"),
                   quantity * Decimal("1e3"),
                   discount * Decimal("1e2"),
                   0, 1, 0,  # increment, fixed 01, zero padding
                   unit[:2],
                   code,
                   description))
        # Uncomment if use CMD_ADD_ITEM: 0x09 (discontinued)
        # data = (
        #     "%-13s"  # code
        #     "%29s"  # description
        #     "%02s"     # taxcode
        #     "%07d"     # quantity
        #     "%08d"     # value
        #     "%08d"    # discount
        # ) % (code, description, taxcode, quantity * Decimal("1e3"),
        #      price * Decimal("1e2"), discount * Decimal("1e2"))
        self._send_command(refund and CMD_ADD_REFUND or CMD_ADD_ITEM, data)
        return self._get_last_item_id()

    def coupon_totalize(self, discount=currency(0), markup=currency(0),
                        taxcode=TaxType.NONE):

        if discount:
            type = 'd'
            value = discount
        elif markup:
            type = 'a'
            value = markup
        else:
            # Just to use the StartClosingCoupon in case of no discount/markup
            # be specified.
            type = 'D'
            value = 0

        self._send_command(CMD_COUPON_TOTALIZE, '%s%04d' % (
            type, int(value * Decimal('1e2'))))

        totalized_value = self._get_coupon_subtotal()
        self.remainder_value = totalized_value
        return totalized_value

    def _read_reply(self, size):
        a = 0
        data = ''
        while True:
            if a > RETRIES_BEFORE_TIMEOUT:
                raise DriverError(_("Timeout communicating with fiscal "
                                    "printer"))

            a += 1
            reply = self.read(size)
            if reply is None:
                continue

            data += reply
            if len(data) < size:
                continue

            log.debug("<<< %r (%d bytes)" % (data, len(data)))
            return data

    def _get_bytes(self, number):
        """
        This funtion is in case the command is 2 bytes length
        if just 1, works too
        """
        if isinstance(number, str):
            ret = number
        elif number == 0:
            ret = chr(number)
        else:
            ret = ''
            while number > 0:
                b = number & 0xFF
                number = number >> 8
                ret = chr(b) + ret
        return ret

    def _send_command(self, command, *args, **kwargs):
        fmt = ''
        if 'response' in kwargs:
            fmt = kwargs.pop('response')

        raw = False
        if 'raw' in kwargs:
            raw = kwargs.pop('raw')

        if kwargs:
            raise TypeError("Invalid kwargs: %r" % (kwargs,))

        cmd = self._get_bytes(command)

        for arg in args:
            if isinstance(arg, int):
                cmd += self._get_bytes(arg)
            elif isinstance(arg, str):
                cmd += arg
            else:
                raise NotImplementedError(type(arg))
        data = self._create_packet(cmd)
        log.debug('Command string: %s', ' '.join(
            [str(hex(ord(char))) for char in cmd]))
        self.write(data)

        format = self.reply_format % fmt
        reply = self._read_reply(struct.calcsize(format))

        retval = struct.unpack(format, reply)
        if raw:
            return retval
        # If just reading a register
        if command != CMD_READ_REGISTER:
            self._check_error(retval)

        response = retval[1:-self.status_size]
        if len(response) == 1:
            response = response[0]
        return response

    def get_status(self, val=None):
        """
        This method is overloaded to use MP4000status class
        """
        if val is None:
            val = self._send_command(CMD_STATUS, raw=True)
        return MP4000Status(val)

    def _read_register(self, reg):
        try:
            fmt, bcd = self.registers.formats[reg]
        except KeyError:
            raise NotImplementedError(reg)
        value = self._send_command(CMD_READ_REGISTER, reg, response=fmt)
        if bcd:
            value = bcd2dec(value)
        return value

    def _get_nit(self):
        return self._read_register(self.registers.NIT)

    def _get_totalizers(self):
        return self._send_command(CMD_READ_TOTALIZERS, response='219s')

    def _get_last_z(self):
        """
        Read some information at the time of the last z

        POS SIZE TYPE DESCRIPTION
        0   1    BIN  00 if Z was commanded. Otherwise, is automatic.
        1   9    BCD  Great total – 18 digits with 2 decimals
        10  7    BCD  Overrides – 14 digits with 2 decimals
        17  7    BCD  Discounts – 14 digits with 2 decimals
        24  32   BCD  16 Taxes with format XX,XX%
        56  112  BCD  16 Totalizers con 14 dígitos con 2 decimales
        168 7    BCD  Reserved
        175 7    BCD  Exempted – 14 digits with 2 decimals
        182 7    BCD  Reserved
        189 7    BCD  Withdrawals – 14 digits with 2 decimals
        196 7    BCD  Cash endowment – 14 digits with 2 decimals
        203 63   BCD  9 Non-fiscal totalizers – 14 digits with 2 decimals
        266 18   BCD  9 Non-fiscal counters
        284 3    BCD  COO - Operation Command Counter (6 digits)
        287 3    BCD  Counter general for non-fiscal operations (6 digits)
        290 1    BIN  Number of programmed taxes
        291 3    BCD  Movement date. DD/MM/AA
        294 7    BCD  Increases – 14 digits with 2 decimals. In case there are
                      no registered last Z Report, the printer returns to the
                      date 00/00/00.
        301 7    BCD  Reserved
        308 9    BCD  IVA total
        317 7    BCD  IVA returned
        """

        if not self._get_last_z_date():
            return []
        res = self._send_command(CMD_LAST_Z, response='324s')
        data = []
        data += [('Z was commanded', bcd2dec(res[0]) == 0)]
        data += [('Great total', bcd2dec(res[1:10]) / Decimal(100))]
        data += [('Overrides', bcd2dec(res[10:17]) / Decimal(100))]
        data += [('Discounts', bcd2dec(res[17:24]) / Decimal(100))]
        taxes = []
        for ind in range(16):
            beg = 24 + ind * 2
            end = beg + 2
            taxes.append(bcd2dec(res[beg:end]) / Decimal(100))
        data += [('Registered taxes', taxes)]
        totalizers = []
        for ind in range(16):
            beg = 56 + ind * 7
            end = beg + 7
            totalizers.append(bcd2dec(res[beg:end]) / Decimal(100))
        data += [('Totalizers', totalizers)]
        data += [('Exempted amount', bcd2dec(res[175:182]) / Decimal(100))]
        data += [('Withdrawals', bcd2dec(res[189:196]) / Decimal(100))]
        data += [('Cash endowment', bcd2dec(res[196:203]) / Decimal(100))]
        tnf = []
        for ind in range(9):
            beg = 203 + ind * 7
            end = beg + 7
            tnf.append(bcd2dec(res[beg:end]) / Decimal(100))
        data += [('Non-fiscal totalizers', tnf)]
        cnf = []
        for ind in range(9):
            beg = 266 + ind * 2
            end = beg + 2
            cnf.append(bcd2dec(res[beg:end]) / Decimal(100))
        data += [('Non-fiscal counters', cnf)]
        data += [('Operation Command Counter (COO)', bcd2dec(res[284:287]))]
        data += [('Counter general for non-fiscal operations',
                  bcd2dec(res[287:290]))]
        data += [('Number of programmed taxes', bcd2dec(res[290]))]
        data += [('Movement date',
                  '%02d/%02d/%02d'
                  % (bcd2dec(res[290]), bcd2dec(res[291]), bcd2dec(res[292])))]
        data += [('Increases (default 00/00/00)',
                  bcd2dec(res[294:301]) / Decimal(100))]
        data += [('IVA total', bcd2dec(res[308:317]) / Decimal(100))]
        data += [('IVA returned', bcd2dec(res[317:324]) / Decimal(100))]
        return data

    def get_cnc(self):
        return self._read_register(self.registers.CNC)

    def _get_last_z_date(self):
        """
        Get date and time of the last reduce z
        and return a datetime object
        """
        last_z_date = self._read_register(self.registers.LAST_Z_DATE)
        date = bcd2hex(last_z_date)
        if not int(date):
            return False
        return datetime.datetime(year=2000 + int(date[4:6]),
                                 month=int(date[2:4]),
                                 day=int(date[:2]),
                                 hour=int(date[6:8]),
                                 minute=int(date[8:10]),
                                 second=int(date[10:12]),)

    def has_pending_reduce(self):
        """ Return true if there is a pending reduce (pending to close till)
        """
        printer_date = self._get_printer_date()
        last_z_date = self._get_last_z_date()
        if not last_z_date:
            return False
        delta_limit = datetime.timedelta(days=1)
        return printer_date > last_z_date + delta_limit

    def get_serial(self):
        """
        Return printer serial number
        """
        return self._read_register(self.registers.SERIAL).strip().strip('\x00')

    def get_tax_constants(self):
        ackd, data = self._send_command(CMD_READ_TAXCODES, response='b32s')

        constants = []
        for i in range(16):
            value = bcd2dec(data[i * 2:i * 2 + 2])
            if not value:
                continue
            tax = TaxType.CUSTOM
            constants.append((tax,
                              '%02d' % (i + 1,),
                              Decimal(value) / 100))

        constants.extend([
            (TaxType.SUBSTITUTION, 'FF', None),
            (TaxType.EXEMPTION, 'II', None),
            (TaxType.NONE, 'NN', None),
        ])

        return constants

    def _set_tax_value(self, value, iva=False):
        """ Set a single tax constant
        """
        data = ("%04d"     # tax rate
                "%s"       # include IVA: 1 - IVA include, 0 - IVA not include
                % (Decimal(value) * Decimal("1e2"), iva and '1' or '0'))
        self._send_command(CMD_ADD_TAX, data, raw=True)

    def _get_tax_value(self, name):
        """ Return a single tax constant
        """
        constants = self.get_tax_constants()
        for ttype, code, value in constants:
            if code == name:
                return value
        return None

    def _set_payment_description(self, name):
        """
        Set a new payment constant
        """
        return self._send_command(CMD_PROGRAM_PAYMENT_METHOD,
                                  '%-16s1' % name[:16], raw=True)

    def set_payment_constants(self, payments):
        """
        Set a list of payment constants
        """
        names = ''.join(['%-16s' % name[:16] for name in payments])
        return self._send_command(CMD_PROGRAM_MULTI_PAYMENT_METHOD,
                                  names, raw=True)

    def get_payment_constants(self):
        """ Return all payment methods
        """
        res = self._read_register(self.registers.PAYMENT_METHODS)
        methods = []
        for i in range(20):
            method = res[i * 16:i * 16 + 16]
            if method != '\x00' * 16:
                code = '%02d' % (i + 1)
                total = bcd2dec(res[i * 7 + 320: i * 7 + 327]) / Decimal(100)
                last = bcd2dec(res[i * 7 + 460: i * 7 + 467]) / Decimal(100)
                tef = res[i + 600] != '\x00'
                methods.append({
                    'code': code,
                    'method': method.strip(),
                    'total': total,
                    'last': last,
                    'tef': tef,
                })
        # just return a tuple with code and description
        return [(m['code'], m['method']) for m in methods]

    def _get_coupon_number(self):
        """
        Get the last coupon number
        """
        coupon_number = self._send_command(
            CMD_GET_COUPON_NUMBER, response='3s')
        return bcd2dec(coupon_number)

    def _get_printer_sensors(self):
        """
        Read sensors status
        """
        sensor = self._read_register(self.registers.PRINTER_SENSORS)
        ret = {}
        ret.update({0: ("Cabezal levantado", sensor & 1 == 1)})
        ret.update({1: ("Tapa abierta", sensor & 2 == 1)})
        ret.update({2: ("Sin papel", sensor & 4 == 1)})
        ret.update({3: ("Poco papel", sensor & 8 == 1)})
        ret.update({4: ("Sensor de gaveta", sensor & 16 == 1)})
        ret.update({5: ("No existe", sensor & 32 == 1)})
        ret.update({6: ("Tecla de papel presionada ", sensor & 64 == 1)})
        ret.update({7: ("Jumper de mantenimiento ", sensor & 128 == 1)})
        return ret

    def _set_fiscal_app(self, name):
        """
        This function can update application name that will be
        printed at the end of boucher
        """
        self._send_command(CMD_FISCAL_APP, "%-84s" % (name))

    def _get_uptime(self):
        """
        Return the time that the printer has been on
        """
        return self._read_register(self.registers.OPERATION_TIME)

    def _set_paper_sensor(self, state=True):
        """
        Set almost out of paper sensor
        """
        value = '1'
        if state:
            value = '0'
        return self._send_command(CMD_PAPER_SENSOR, "%1s" % (value), raw=True)

    def _set_z_time_limit(self, time):
        """
        Set Z time limit
        """
        return self._send_command(CMD_Z_TIME_LIMIT, "%02d" % (time), raw=True)

    def _set_td_ecv(self, till, store):
        """
        Set till and store numbers
        """
        return self._send_command(CMD_TD_ECV, "%04d%04d" % (till, store),
                                  raw=True)

    def _read_transactions(self, start, end, dest='R'):
        """
        Returns a string with all transactions from a given range
        """
        cmd = self._get_bytes(CMD_TRANSACTIONS)
        if isinstance(start, datetime.datetime) and \
                isinstance(end, datetime.datetime):
            cmd += '%6s%6s' % (start.strftime('%d%m%y'),
                               end.strftime('%d%m%y'))
        else:
            cmd += '00%04d00%04d' % (start, end)
        cmd += dest
        # print cmd
        data = self._create_packet(cmd)
        self.write(data)
        if dest == 'I':
            return True
        res = ''
        cha = '0'
        while True:
            cha = self.read(1)
            if cha == chr(ECK):
                break
            res += unicode(cha, self.coupon_printer_charset)
        res = res[3:]
        return res

    def _get_transactions(self, start, end):
        """
        Returns a dictionary with all transactions in a given period
        """
        res = self._read_transactions(start, end)
        res = res.split('\n')
        data = {'invoices': []}
        f = {}
        for t in res[11:]:
            conts = [m for m in t.split(' ') if m]
            if conts:
                # print "Linea ", conts
                if 'COO:' in conts[0]:
                    if f:
                        data['invoices'].append(f)
                    f = {'payments': {}, 'cancel': {}}
                    temp = conts[0].split(':')
                    f.update({temp[0]: temp[1]})
                    temp = conts[1].split(':')
                    f.update({temp[0]: temp[1]})
                    temp = ['date', datetime.datetime.strptime(
                        '%s %s' % (conts[2], conts[3]), '%d/%m/%Y %H:%M:%S')]
                    f.update({temp[0]: temp[1]})
                elif re.search(r'^(-|)[0-9]{1,},[0-9]{1,}$', conts[-1]) and \
                        conts[-2] == '=':
                    temp = [' '.join(conts[:-2]),
                            float(conts[-1].replace(',', '.'))]
                    f['payments'].update({temp[0]: temp[1]})
                elif 'ANULACI' in conts[0]:
                    temp = conts[1].split(':')
                    f['cancel'].update({temp[0]: temp[1]})
                    temp = ['date', datetime.datetime.strptime(
                        '%s %s' % (conts[2], conts[3]), '%d/%m/%Y %H:%M:%S')]
                    f['cancel'].update({temp[0]: temp[1]})
                elif 'Factura' in conts[0] and 'Inicial' in conts[1]:
                    data.update({'start': int(conts[2])})
                elif 'Factura' in conts[0] and 'Final' in conts[1]:
                    data.update({'end': int(conts[2])})
                elif len(conts) > 3 and 'Facturas' in conts[2] and \
                        'mero' in conts[0] and 'Anuladas' in conts[3]:
                    data.update({'ncancels': int(conts[4])})
                elif len(conts) > 3 and 'Facturas' in conts[2] and \
                        'mero' in conts[0]:
                    data.update({'ninvoices': int(conts[3])})
                elif 'VERSI' in conts[0] and 'CAJA' in conts[1] and \
                        'TIENDA' in conts[2]:
                    temp = conts[1].split(':')
                    data.update({'till': int(temp[1])})
                    temp = conts[2].split(':')
                    data.update({'store': int(temp[1])})
        if f:
            data['invoices'].append(f)
        return data

    def get_capabilities(self):
        """
        Fields size for this printer
        """
        return dict(
            item_code=Capability(max_len=49),
            item_id=Capability(digits=4),
            items_quantity=Capability(min_size=1, digits=4, decimals=2),
            item_price=Capability(digits=8, decimals=3),
            item_description=Capability(max_len=201),
            payment_value=Capability(digits=12, decimals=2),
            promotional_message=Capability(max_len=320),
            payment_description=Capability(max_len=80),
            customer_name=Capability(max_len=41),
            customer_id=Capability(max_len=18),
            customer_address=Capability(max_len=133),
            add_cash_value=Capability(min_size=0.1, digits=12, decimals=2),
            remove_cash_value=Capability(min_size=0.1, digits=12, decimals=2),
        )


class MP4000Status(object):
    PENDING_REDUCE_Z = 66

    st1_codes = {
        128: (OutofPaperError(_("Printer is out of paper"))),
        64: (AlmostOutofPaper(_("Printer almost out of paper"))),
        32: (PrinterError(_("Printer clock error"))),
        16: (PrinterError(_("Printer in error state"))),
        8: (CommandError(_("First data value in CMD is not ESC (1BH)"))),
        4: (CommandError(_("Nonexistent command"))),
        2: (CouponOpenError(_("Printer has a coupon currently open"))),
        1: (CommandError(_("Invalid CMD parameter number")))
    }

    st2_codes = {
        128: (CommandError(_("Invalid CMD parameter"))),
        64: (HardwareFailure(_("Fiscal memory is full"))),
        32: (HardwareFailure(_("Error in CMOS memory"))),
        16: (PrinterError(_("Given tax is not programmed on the printer"))),
        8: (DriverError(_("No available tax slot"))),
        4: (CancelItemError(_("The item wasn't added in the coupon or can't "
                              "be cancelled"))),
        2: (PrinterError(_("Owner data (CGC/IE) not programmed on the "
                           "printer"))),
        1: (CommandError(_("Command not executed")))
    }

    st3_codes = {
        7: (CouponOpenError(_("Coupon already Open"))),
        8: (CouponNotOpenError(_("Coupon is closed"))),
        13: (PrinterOfflineError(_("Printer is offline"))),
        16: (DriverError(_("Surcharge or discount greater than coupon total"
                           "value"))),
        17: (DriverError(_("Coupon with no items"))),
        20: (PaymentAdditionError(_("Payment method not recognized"))),
        22: (PaymentAdditionError(_("Isn't possible add more payments since"
                                    "the coupon total value already was "
                                    "reached"))),
        23: (DriverError(_("Coupon isn't totalized yet"))),
        43: (CouponNotOpenError(_("Printer not initialized"))),
        45: (PrinterError(_("Printer without serial number"))),
        52: (DriverError(_("Invalid start date"))),
        53: (DriverError(_("Invalid final date"))),
        85: (DriverError(_("Sale with null value"))),
        91: (ItemAdditionError(_("Surcharge or discount greater than item"
                                 "value"))),
        100: (DriverError(_("Invalid date"))),
        115: (CancelItemError(_("Item doesn't exists or already was "
                                "cancelled"))),
        118: (DriverError(_("Surcharge greater than item value"))),
        119: (DriverError(_("Discount greater than item value"))),
        129: (CouponOpenError(_("Invalid month"))),
        169: (CouponTotalizeError(_("Coupon already totalized"))),
        170: (PaymentAdditionError(_("Coupon not totalized yet"))),
        171: (DriverError(_("Surcharge on subtotal already effected"))),
        172: (DriverError(_("Discount on subtotal already effected"))),
        176: (DriverError(_("Invalid date")))}

    def __init__(self, reply):
        #        print "Status ", reply
        self.st = reply[0]
        self.st_descr = len(reply) > 3 and reply[1:-2] or []
        self.st1, self.st2 = reply[-2:]

    @property
    def open(self):
        """
        Verify if coupon is open
        """
        return self.st1 & 2

    def _check_error_in_dict(self, error_codes, value):
        """
        Return a exception according to error code
        """
        for key in error_codes:
            if key & value:
                raise error_codes[key]

    def check_error(self):
        """
        Verify printer status
        """
        status = "st=%s st1=%s st2=%s" % (self.st, self.st1, self.st2)
        log.debug("status: %s", status)
        # print "status: st=%s st1=%s st2=%s" % (self.st_descr, self.st1,
        # self.st2)
        # if self.st != ACK:

        if self.st1 != 0:
            self._check_error_in_dict(self.st1_codes, self.st1)

        if self.st2 != 0:
            self._check_error_in_dict(self.st2_codes, self.st2)

            # first bit means not executed, look in st3 for more
            # if self.st2 & 1 and self.st_descr:
            #     if self.st_descr in self.st3_codes:
            #         raise self.st3_codes[self.st3]

    def cancel_last_coupon(self):
        """Cancel the last non fiscal coupon or the last sale."""
        # XXX MP4000 does not support this
        self.coupon_cancel()
