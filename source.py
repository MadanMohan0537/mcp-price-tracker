"""Explicit host allowlist, public DNS validation, pinned TLS connection, no redirects."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlparse


def fetch_page(url, allowed_hosts):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.hostname not in allowed_hosts:
        raise ValueError("Source is not configured in PRICE_ALLOWED_HOSTS")
    answers = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Source must resolve only to public addresses")
    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            self.sock = self._context.wrap_socket(socket.create_connection((addresses[0],443), self.timeout), server_hostname=parsed.hostname)
    connection = PinnedHTTPS(parsed.hostname, timeout=10, context=ssl.create_default_context())
    try:
        connection.request("GET", (parsed.path or "/") + ("?"+parsed.query if parsed.query else ""), headers={"User-Agent":"MCPPriceTracker/1.0", "Accept":"text/html"})
        response = connection.getresponse()
        if response.status != 200: raise ValueError(f"Source returned HTTP {response.status}; redirects are not followed")
        if "text/html" not in response.getheader("Content-Type", ""): raise ValueError("Source must return HTML")
        body = response.read(800001)
        if len(body)>800000: raise ValueError("Source page exceeds 800 KB")
        return body.decode("utf-8")
    finally: connection.close()
