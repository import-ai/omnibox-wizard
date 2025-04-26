from testcontainers.chroma import ChromaContainer as ChromaContainerV1
from testcontainers.core.waiting_utils import wait_container_is_ready
from requests import ConnectionError, get, Response


class ChromaContainer(ChromaContainerV1):
    @wait_container_is_ready(ConnectionError)
    def _healthcheck(self) -> None:
        """This is an internal method used to check if the Chroma container
        is healthy and ready to receive requests."""
        url = f"http://{self.get_config()['endpoint']}/api/v2/healthcheck"
        response: Response = get(url)
        response.raise_for_status()


__all__ = ["ChromaContainer"]
