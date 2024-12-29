class BaseFunction:
    async def run(self, input_data: dict) -> dict:
        raise NotImplementedError