#              .';:cc;.
#            .,',;lol::c.
#            ;';lddddlclo
#            lcloxxoddodxdool:,.
#            cxdddxdodxdkOkkkkkkkd:.
#          .ldxkkOOOOkkOO000Okkxkkkkx:.
#        .lddxkkOkOOO0OOO0000Okxxxxkkkk:
#       'ooddkkkxxkO0000KK00Okxdoodxkkkko
#      .ooodxkkxxxOO000kkkO0KOxolooxkkxxkl
#      lolodxkkxxkOx,.      .lkdolodkkxxxO.
#      doloodxkkkOk           ....   .,cxO;
#      ddoodddxkkkk:         ,oxxxkOdc'..o'
#      :kdddxxxxd,  ,lolccldxxxkkOOOkkkko,
#       lOkxkkk;  :xkkkkkkkkOOO000OOkkOOk.
#        ;00Ok' 'O000OO0000000000OOOO0Od.
#         .l0l.;OOO000000OOOOOO000000x,
#            .'OKKKK00000000000000kc.
#               .:ox0KKKKKKK0kdc,.
#                      ...
#
# Author: peppe8o (Giuseppe Cassibba)
# Blog: https://peppe8o.com
# p8o-pico: single-file MicroPython utilities

__version__ = '0.1'

class LedBar:
    """Ten segments ordered highest to lowest; one resistor per segment."""
    def __init__(self, pins, common_anode=True):
        from machine import Pin
        pins = tuple(pins)
        if len(pins) != 10 or len(set(pins)) != 10:
            raise ValueError('Expected ten distinct GPIO numbers')
        self.common_anode = bool(common_anode)
        self._leds = [Pin(pin, Pin.OUT, value=int(self.common_anode)) for pin in pins]

    def led_bar_show(self, pattern):
        """Display ten binary states; 1 always means on."""
        pattern = tuple(pattern)
        if len(pattern) != 10 or any(v not in (0, 1) for v in pattern):
            raise ValueError('Expected ten binary states')
        for led, state in zip(self._leds, pattern):
            led.value(not state if self.common_anode else state)

    def led_bar_percentage(self, percentage):
        """One segment per completed 10 percent, filling from the bottom."""
        if type(percentage) is not int or not 0 <= percentage <= 100:
            raise ValueError('Expected an integer from 0 to 100')
        self.led_bar_show([int(percentage >= t) for t in (100,90,80,70,60,50,40,30,20,10)])

    def off(self):
        self.led_bar_show([0] * 10)

    def on(self):
        self.led_bar_show([1] * 10)

    def cycle(self, delay_ms=50, cycles=None):
        """Blocking local animation; always switch off on exit."""
        import time
        if type(delay_ms) is not int or delay_ms < 0:
            raise ValueError('delay_ms must be a nonnegative integer')
        if cycles is not None and (type(cycles) is not int or cycles < 1):
            raise ValueError('cycles must be None or a positive integer')
        completed = 0
        try:
            while cycles is None or completed < cycles:
                for index in range(10):
                    pattern = [0] * 10
                    pattern[index] = 1
                    self.led_bar_show(pattern)
                    time.sleep_ms(delay_ms)
                completed += 1
        finally:
            self.off()


class WebLedBar(LedBar):
    """HTTP LED control for trusted local networks; no authentication/TLS."""
    def connect_wifi(self, ssid, password, country='IT', power_save=False,
                     timeout=20, verbose=False, reset=False):
        """Connect and return the IP. Log status without exposing password.

        reset=True explicitly disables/re-enables the interface before joining.
        Timeout applies to the connection wait after connect() returns.
        """
        import network
        import rp2
        import time
        if timeout <= 0:
            raise ValueError('timeout must be positive')
        def log(*args):
            if verbose:
                print('[Wi-Fi]', *args)
        def status_text():
            code = self._wlan.status()
            names = ('STAT_IDLE', 'STAT_CONNECTING', 'STAT_WRONG_PASSWORD',
                     'STAT_NO_AP_FOUND', 'STAT_CONNECT_FAIL', 'STAT_GOT_IP')
            name = next((n for n in names if getattr(network, n, None) == code), 'UNKNOWN')
            return '%s (%s)' % (name, code)
        rp2.country(country)
        self._wlan = network.WLAN(network.STA_IF)
        log('Country:', country, '| SSID:', repr(ssid))
        if reset:
            log('Resetting Wi-Fi interface')
            self._wlan.active(False)
            time.sleep_ms(200)
        self._wlan.active(True)
        log('Interface active:', self._wlan.active())
        if not power_save:
            self._wlan.config(pm=network.WLAN.PM_NONE)
        log('Power saving:', 'default/current setting' if power_save else 'disabled')
        if not self._wlan.isconnected():
            log('Connecting; timeout:', timeout, 'seconds')
            try:
                self._wlan.connect(ssid, password)
                start = time.ticks_ms()
                last_log = -1000
                while not self._wlan.isconnected():
                    elapsed = time.ticks_diff(time.ticks_ms(), start)
                    if elapsed - last_log >= 1000:
                        log('Elapsed: %.1f s | Status: %s' % (elapsed / 1000, status_text()))
                        last_log = elapsed
                    if elapsed >= timeout * 1000:
                        final_status = status_text()
                        log('Timed out | Final status:', final_status)
                        self._wlan.disconnect()
                        raise RuntimeError('Wi-Fi connection timed out: ' + final_status)
                    time.sleep_ms(200)
            except Exception as error:
                log('Connection error:', repr(error))
                raise
        else:
            log('Reusing existing connection; credentials not revalidated')
        config = self._wlan.ifconfig()
        self.ip_address = config[0]
        log('Connected | IP:', config[0], '| Mask:', config[1], '| Gateway:', config[2], '| DNS:', config[3])
        try:
            log('RSSI:', self._wlan.status('rssi'))
        except (OSError, ValueError, AttributeError):
            pass
        return self.ip_address

    @staticmethod
    def _decode_query(text):
        result = bytearray()
        index = 0
        while index < len(text):
            if text[index] == '%':
                if index + 2 >= len(text):
                    raise ValueError('Incomplete URL escape')
                result.append(int(text[index + 1:index + 3], 16))
                index += 3
            else:
                result.append(32 if text[index] == '+' else ord(text[index]))
                index += 1
        return result.decode()

    def _execute_command(self, target):
        if not target.startswith('/?'):
            raise ValueError('Missing command')
        name, argument = self._decode_query(target[2:]).strip().split('(', 1)
        if not argument.endswith(')'):
            raise ValueError('Missing closing parenthesis')
        argument = argument[:-1].strip()
        if name == 'led_bar_show':
            if not (argument.startswith('[') and argument.endswith(']')):
                raise ValueError('Expected a list')
            self.led_bar_show([int(item) for item in argument[1:-1].split(',')])
        elif name == 'led_bar_percentage':
            self.led_bar_percentage(int(argument))
        else:
            raise ValueError('Unknown command')

    @staticmethod
    def _read_headers(client):
        import time
        data = bytearray()
        start = time.ticks_ms()
        while b'\r\n\r\n' not in data:
            remaining = 3000 - time.ticks_diff(time.ticks_ms(), start)
            if remaining <= 0 or len(data) >= 2048:
                raise ValueError('Incomplete or oversized request')
            client.settimeout(remaining / 1000)
            chunk = client.recv(min(512, 2048 - len(data)))
            if not chunk:
                raise ValueError('Client disconnected')
            data.extend(chunk)
        return bytes(data)

    def _serve_client(self, client):
        try:
            request = self._read_headers(client)
            target = request.split(b'\r\n', 1)[0].split()[1].decode('ascii')
            self._execute_command(target)
            status, body = '200 OK', 'success'
        except (ValueError, IndexError, UnicodeError):
            status, body = '400 Bad Request', 'errore'
        response = ('HTTP/1.1 ' + status + '\r\n'
                    'Content-Type: text/plain; charset=utf-8\r\n'
                    'Content-Length: ' + str(len(body)) + '\r\n'
                    'Cache-Control: no-store\r\n'
                    'Connection: close\r\n\r\n' + body)
        client.settimeout(3)
        client.write(response.encode())

    def serve(self, port=80):
        """Serve until interrupted; cycle() is not exposed over HTTP."""
        import socket
        if not hasattr(self, '_wlan') or not self._wlan.isconnected():
            raise RuntimeError('Call connect_wifi() before serve()')
        server = socket.socket()
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('0.0.0.0', port))
            server.listen(3)
            print('Web server listening on http://%s:%s' % (self._wlan.ifconfig()[0], port))
            while True:
                client = None
                try:
                    client, address = server.accept()
                    self._serve_client(client)
                except Exception as error:
                    print('Request error:', repr(error))
                finally:
                    if client is not None:
                        try:
                            client.close()
                        except OSError:
                            pass
        except KeyboardInterrupt:
            print('Server stopped')
        finally:
            server.close()
