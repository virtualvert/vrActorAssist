from agent.actor_runtime import osc_address, osc_value


def test_osc_address_shorthand():
    assert osc_address("RecIcon") == "/avatar/parameters/RecIcon"
    assert osc_address("/avatar/parameters/X") == "/avatar/parameters/X"


def test_osc_values_are_typed():
    assert osc_value("true") is True
    assert osc_value("False") is False
    assert osc_value("0.75") == 0.75
    assert osc_value("3") == 3 and isinstance(osc_value("3"), int)
    assert osc_value("-1") == -1
    assert osc_value("hello") == "hello"
