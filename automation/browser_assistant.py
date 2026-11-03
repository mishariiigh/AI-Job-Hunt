class BrowserAssistant:
    def __init__(self):
        self.playwright_available = False
    
    def start(self, url):
        # Only for permitted workflows
        raise NotImplementedError("Implement with permission checks")
    
    def stop(self):
        pass
