import asyncio
import json
import socket
import time

from app.utility.base_world import BaseWorld
from plugins.terminal.app.c_session import Session


class Sockit(BaseWorld):

    def __init__(self, services):
        self.name = 'tcp'
        self.log = self.create_logger('sockit')
        self.contact_svc = services.get('contact_svc')
        self.tcp_port = services.get('app_svc').config['secrets']['terminal']['tcp_port']
        self.udp_port = services.get('app_svc').config['secrets']['terminal']['udp_port']
        terminal_keys = services.get('app_svc').config['secrets']['terminal']['terminal_keys']
        self.tcp_handler = TcpSessionHandler(services, terminal_keys)
        self.udp_handler = UdpSessionHandler(services)

    def start(self):
        loop = asyncio.get_event_loop()
        loop.create_task(asyncio.start_server(self.tcp_handler.accept, '0.0.0.0', self.tcp_port, loop=loop))
        loop.create_task(loop.create_datagram_endpoint(lambda: self.udp_handler, local_addr=('0.0.0.0', self.udp_port)))
        loop.create_task(self.operation_loop())

    async def operation_loop(self):
        while True:
            for session in self.tcp_handler.sessions:
                _, instructions = await self.contact_svc.handle_heartbeat(paw=session.paw)
                for instruction in instructions:
                    try:
                        self.log.debug('TCP instruction: %s' % instruction.id)
                        status, response = await self.tcp_handler.send(session.id, self.decode_bytes(instruction.command))
                        await self.contact_svc.save_results(id=instruction.id, output=self.encode_string(response), status=status, pid=0)
                        await asyncio.sleep(instruction.sleep)
                    except Exception as e:
                        self.log.debug('[-] operation exception: %s' % e)
            await asyncio.sleep(20)

    @staticmethod
    def valid_config():
        return True


class TcpSessionHandler(BaseWorld):

    def __init__(self, services, terminal_keys):
        self.log = self.create_logger('tcp_session')
        self.services = services
        self.terminal_keys = terminal_keys
        self.sessions = []
        self.seen_ips = set()

    async def refresh(self):
        for index, session in enumerate(self.sessions):
            try:
                session.connection.send(str.encode(' '))
            except socket.error:
                del self.sessions[index]

    async def accept(self, reader, writer):
        try:
            profile = await self._handshake(reader)
        except Exception as e:
            self.log.debug('Handshake failed: %s' % e)
            return
        connection = writer.get_extra_info('socket')
        profile['executors'] = [e for e in profile['executors'].split(',') if e]
        profile['contact'] = 'tcp'
        agent, instructions = await self.services.get('contact_svc').handle_heartbeat(**profile)
        new_session = Session(id=len(self.sessions) + 1, paw=agent.paw, connection=connection)
        self.sessions.append(new_session)
        await self.send(new_session.id, agent.paw)

    async def send(self, session_id, cmd):
        try:
            conn = next(i.connection for i in self.sessions if i.id == int(session_id))
            conn.send(str.encode(' '))
            conn.send(str.encode('%s\n' % cmd))
            response = await self._attempt_connection(conn, 100)
            response = json.loads(response)
            return response['status'], response['response']
        except Exception as e:
            return 1, e

    """ PRIVATE """

    @staticmethod
    async def _handshake(reader):
        profile_bites = (await reader.readline()).strip()
        return json.loads(profile_bites)

    @staticmethod
    async def _attempt_connection(connection, max_tries):
        attempts = 0
        client_response = None
        while not client_response:
            try:
                client_response = str(connection.recv(4096), 'utf-8')
            except BlockingIOError as err:
                if attempts > max_tries:
                    raise err
                attempts += 1
                time.sleep(.1 * attempts)
        return client_response


class UdpSessionHandler(asyncio.DatagramProtocol):

    def __init__(self, services):
        super().__init__()
        self.log = BaseWorld.create_logger('udp_session')
        self.contact_svc = services.get('contact_svc')

    def datagram_received(self, data, addr):
        async def handle_beacon():
            try:
                # save beacon
                profile = json.loads(data.decode())
                callback = profile.pop('callback')
                profile['executors'] = [e for e in profile['executors'].split(',') if e]
                profile['contact'] = 'udp'
                agent, _ = await self.contact_svc.handle_heartbeat(**profile)

                # send confirmation
                sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
                sock.sendto('roger'.encode(), (addr[0], int(callback)))
            except Exception as e:
                self.log.debug(e)
        asyncio.get_event_loop().create_task(handle_beacon())