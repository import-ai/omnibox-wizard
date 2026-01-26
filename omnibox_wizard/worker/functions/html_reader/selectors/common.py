from omnibox_wizard.worker.functions.html_reader.selectors.lambda_selector import (
    LambdaSelector,
)


class CommonSelector(LambdaSelector):
    def __init__(self, domain: str, selector: dict, select_all: bool = False) -> None:
        self.domain: str = domain
        super().__init__(lambda p, s: p.netloc == domain, selector, select_all)
