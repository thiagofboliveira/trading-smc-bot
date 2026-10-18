from smc_trader.zones.premium_discount import equilibrium, in_discount


def test_equilibrium():
    assert equilibrium(10, 13.5) == 11.75


def test_in_discount_long():
    assert in_discount("long", 10, 12, 10, 13.5) is True
    assert in_discount("long", 12.5, 13, 10, 13.5) is False


def test_in_premium_short():
    assert in_discount("short", 12.5, 13, 10, 13.5) is True
