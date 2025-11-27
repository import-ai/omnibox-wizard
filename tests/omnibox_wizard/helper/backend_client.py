import httpx
import shortuuid


class BackendClient(httpx.Client):
    def __init__(self, delete_user: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.delete_user: bool = delete_user

        self.username: str = shortuuid.uuid()
        self.email: str = shortuuid.uuid() + "@example.com"
        self.password: str = shortuuid.uuid()

        response: httpx.Response = self.post(
            "/internal/api/v1/sign-up",
            json={
                "username": self.username,
                "password": self.password,
                "password_repeat": self.password,
                "email": self.email,
            },
        )
        signup_result: dict = response.json()
        assert response.status_code == 201, signup_result

        self.user_id: int = signup_result["id"]
        self.access_token: str = signup_result["access_token"]
        assert self.username == signup_result["username"]

        self.headers["Authorization"] = f"Bearer {self.access_token}"

        response: httpx.Response = self.get("/api/v1/namespaces")
        assert response.is_success, response.text
        namespace_list_result: dict = response.json()
        assert len(namespace_list_result) > 0
        namespace: dict = namespace_list_result[0]
        self.namespace_id: str = namespace["id"]

        response: httpx.Response = self.get(
            f"/api/v1/namespaces/{self.namespace_id}/root"
        )
        assert response.is_success, response.text
        json_response: dict = response.json()
        self.private_root_id: str = json_response["private"]["id"]
        self.teamspace_root_id: str = json_response["teamspace"]["id"]

    def __enter__(self) -> "BackendClient":
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        if self.delete_user:
            response: httpx.Response = self.delete(f"/api/v1/user/{self.user_id}")
            assert response.status_code == 200, response.json()

    def parent_id(self, space_type: str) -> str:
        response = self.get(
            f"/api/v1/namespaces/{self.namespace_id}/resources/root",
            params={"namespace_id": self.namespace_id, "space_type": space_type},
        )
        return response.json()["id"]
