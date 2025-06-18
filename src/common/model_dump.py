def model_dump(obj, exclude_none: bool = True, *args, **kwargs) -> dict | list:
    if isinstance(obj, list):
        return [model_dump(item, exclude_none=exclude_none, *args, **kwargs) for item in obj]
    elif hasattr(obj, 'model_dump'):
        return obj.model_dump(exclude_none=exclude_none, *args, **kwargs)
