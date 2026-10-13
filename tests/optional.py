"""Optional dependency metadata shared by unittest and the tier runner."""
from importlib.util import find_spec


def available(*modules):
    return all(find_spec(name) is not None for name in modules)


def requires(*modules):
    def annotate(test):
        test.requires = tuple(sorted(set(getattr(test, "requires", ())) | set(modules)))
        return test
    return annotate
