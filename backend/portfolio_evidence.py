"""Delay large persisted overlay evidence until its nonblocking source read succeeds."""


class PortfolioEvidence(dict):
    def __init__(self, state, load):
        super().__init__(state)
        self.load = load

    def _ensure(self, key):
        if self.load is not None and key in {'projects', 'source_confirmations', 'contract_items', 'source_work_items'}:
            load, self.load = self.load, None
            self.update(load())

    def get(self, key, default=None):
        self._ensure(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self._ensure(key)
        return super().__getitem__(key)
