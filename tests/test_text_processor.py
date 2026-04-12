from verbal_code.injector import TextProcessor


class TestTextProcessor:
    def test_capitalizes_first_word(self):
        tp = TextProcessor()
        assert tp.process("hello") == "Hello "

    def test_adds_trailing_space(self):
        tp = TextProcessor()
        assert tp.process("Hello").endswith(" ")

    def test_does_not_double_space(self):
        tp = TextProcessor()
        assert tp.process("hello ") == "Hello "

    def test_second_call_no_capitalize(self):
        tp = TextProcessor()
        tp.process("hello")
        assert tp.process("world") == "world "

    def test_reset_re_enables_capitalize(self):
        tp = TextProcessor()
        tp.process("hello")
        tp.reset()
        assert tp.process("world") == "World "

    def test_empty_string_returns_empty(self):
        tp = TextProcessor()
        assert tp.process("") == ""

    def test_single_char(self):
        tp = TextProcessor()
        assert tp.process("a") == "A "

    def test_already_capitalized(self):
        tp = TextProcessor()
        assert tp.process("Hello") == "Hello "
