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


class TestPunctuationCommands:
    def test_period_attaches_and_capitalizes_next(self):
        tp = TextProcessor()
        assert tp.process("hello period how are you") == "Hello. How are you "

    def test_full_stop_alias(self):
        tp = TextProcessor()
        assert tp.process("hello full stop") == "Hello. "

    def test_comma(self):
        tp = TextProcessor()
        assert tp.process("first comma second") == "First, second "

    def test_question_mark(self):
        tp = TextProcessor()
        assert tp.process("ready question mark") == "Ready? "

    def test_exclamation_variants(self):
        tp = TextProcessor()
        assert tp.process("wow exclamation mark") == "Wow! "
        tp.reset()
        assert tp.process("wow exclamation point") == "Wow! "

    def test_colon_semicolon_ellipsis(self):
        tp = TextProcessor()
        assert tp.process("note colon items semicolon more ellipsis") == (
            "Note: items; more... "
        )

    def test_new_line(self):
        tp = TextProcessor()
        assert tp.process("first line new line second line") == (
            "First line\nSecond line "
        )

    def test_newline_single_word_alias(self):
        tp = TextProcessor()
        assert tp.process("alpha newline beta") == "Alpha\nBeta "

    def test_new_paragraph(self):
        tp = TextProcessor()
        assert tp.process("one new paragraph two") == "One\n\nTwo "

    def test_segment_ending_in_newline_gets_no_trailing_space(self):
        tp = TextProcessor()
        assert tp.process("hello new line") == "Hello\n"

    def test_capitalizes_across_segments_after_sentence_end(self):
        tp = TextProcessor()
        assert tp.process("first sentence period") == "First sentence. "
        assert tp.process("second sentence") == "Second sentence "

    def test_no_cross_segment_capitalize_mid_sentence(self):
        tp = TextProcessor()
        tp.process("hello")
        assert tp.process("world") == "world "

    def test_stt_punctuation_on_command_word_not_doubled(self):
        tp = TextProcessor()
        # Whisper often emits "period." with its own punctuation attached.
        assert tp.process("hello period.") == "Hello. "

    def test_commands_case_insensitive(self):
        tp = TextProcessor()
        assert tp.process("hello Period next") == "Hello. Next "

    def test_disabled_commands_type_literally(self):
        tp = TextProcessor(punctuation_commands=False)
        assert tp.process("hello period how") == "Hello period how "

    def test_command_only_segment(self):
        tp = TextProcessor()
        tp.process("hello")
        assert tp.process("period") == ". "
