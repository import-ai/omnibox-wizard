from requests import ConnectionError, get, Response
from testcontainers.chroma import ChromaContainer as ChromaContainerV1
from testcontainers.core.waiting_utils import wait_container_is_ready


class ChromaContainer(ChromaContainerV1):

    def _health_url(self):
        version: str = self.image.split(':')[-1].strip()
        if version.startswith('0.'):
            return f"http://{self.get_config()['endpoint']}/api/v1/heartbeat"
        return f"http://{self.get_config()['endpoint']}/api/v2/healthcheck"

    @wait_container_is_ready(ConnectionError)
    def _healthcheck(self) -> None:
        """This is an internal method used to check if the Chroma container
        is healthy and ready to receive requests."""
        response: Response = get(self._health_url())
        response.raise_for_status()


__all__ = ["ChromaContainer"]
