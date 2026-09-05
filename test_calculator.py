from calculator import add, multiply, divide


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(2, 3) == 6


def test_divide():
    assert divide(10, 2) == 5


def test_divide_by_zero():
    try:
        divide(10, 0)
    except ZeroDivisionError:
        pass
    else:
        raise AssertionError("divide by zero must raise ZeroDivisionError")


def test_hidden_bug():
    assert add(10, 5) == 15