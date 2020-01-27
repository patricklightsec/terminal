from shutil import which

from aiohttp_jinja2 import template

from app.utility.base_service import BaseService


class TermApi(BaseService):

    def __init__(self, services, tcp_conn):
        self.log = self.add_service('term_api', self)
        self.auth_svc = services.get('auth_svc')
        self.file_svc = services.get('file_svc')
        self.contact_svc = services.get('contact_svc')
        self.tcp_conn = tcp_conn

    @template('terminal.html')
    async def splash(self, request):
        await self.auth_svc.check_permissions(request)
        await self.tcp_conn.handler.refresh()
        return dict(sessions=[dict(id=s.id, info=s.paw) for s in self.tcp_conn.handler.sessions])

    async def dynamically_compile(self, headers):
        name, platform = headers.get('file'), headers.get('platform')
        if which('go') is not None:
            plugin, file_path = await self.file_svc.find_file_path(name)
            ldflags = ['-s', '-w', '-X main.key=%s' % self.generate_name(size=30)]
            output = 'plugins/%s/payloads/%s-%s' % (plugin, name, platform)
            self.log.debug('Dynamically compiling %s' % name)
            await self.file_svc.compile_go(platform, output, file_path, ldflags=' '.join(ldflags))
        return '%s-%s' % (name, platform), self.generate_name(10)

    async def socket_handler(self, socket, path):
        try:
            session_id = path.split('/')[1]
            cmd = await socket.recv()
            paw, status, reply = await self.tcp_conn.handler.send(session_id, cmd)
            await self.contact_svc.handle_heartbeat(**dict(paw=paw))
            await socket.send(reply.strip())
        except Exception:
            await socket.send('CONNECTION LOST!')