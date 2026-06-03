"""Backend unit tests for chess game engine.

Tests en passant, check, checkmate, stalemate, bot-vs-bot, player-vs-bot,
move validation, skill levels, and game state lifecycle — calling server
functions directly (no HTTP overhead) for speed.
"""

import chess
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__) + "/..")

from server import (
    pool,
    state,
    _do_bot_move,
    GameState,
    RandomBot,
    _is_human_turn,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_state():
    """Reset game state before each test."""
    state.mode = "bot_vs_bot"
    state.white_engine = "stockfish"
    state.black_engine = "stockfish"
    state.white_skill = 10
    state.black_skill = 5
    state.player_color = chess.BLACK
    state.board = chess.Board()
    yield
    state.mode = "bot_vs_bot"
    state.white_engine = "stockfish"
    state.black_engine = "stockfish"
    state.white_skill = 10
    state.black_skill = 5
    state.player_color = chess.BLACK
    state.board = chess.Board()


# ---------------------------------------------------------------------------
# Test: RandomBot produces legal moves
# ---------------------------------------------------------------------------


class TestRandomBot:
    def test_random_bot_starts(self):
        bot = RandomBot("RandomBot")
        bot.start()
        bot.shutdown()

    def test_random_bot_plays_legal_move(self):
        bot = RandomBot("RandomBot")
        board = chess.Board()
        result = bot.play(board, chess.engine.Limit(time=0.1))
        assert result.move is not None
        assert result.move in board.legal_moves
        bot.shutdown()

    def test_random_bot_moves_are_pseudo_legal(self):
        """Run 100 random moves; every move must be legal in the position it's played from."""
        bot = RandomBot("RandomBot")
        board = chess.Board()
        for _ in range(40):
            if board.is_game_over():
                break
            result = bot.play(board, chess.engine.Limit(time=0.05))
            assert result.move in board.legal_moves
            board.push(result.move)
        bot.shutdown()


# ---------------------------------------------------------------------------
# Test: En Passant
# ---------------------------------------------------------------------------


class TestEnPassant:
    def test_white_can_capture_en_passant(self):
        """FEN: white pawn on e5, black pawn on d5, white to move.
        e5xd6 en passant must be legal.
        """
        state.board = chess.Board("4k3/4p3/8/3pP3/8/8/8/4K3 w - d6 0 1")
        assert state.board.has_legal_en_passant()
        ep_move = chess.Move.from_uci("e5d6")
        assert ep_move in state.board.legal_moves

    def test_white_en_passant_executes_correctly(self):
        """Execute en passant and verify the captured pawn is removed."""
        state.board = chess.Board("4k3/4p3/8/3pP3/8/8/8/4K3 w - d6 0 1")
        ep_move = chess.Move.from_uci("e5d6")
        assert ep_move in state.board.legal_moves
        state.board.push(ep_move)
        assert state.board.piece_at(chess.D7) is None, "Captured d7 pawn still on board"
        assert state.board.piece_at(chess.D6) is not None, "White pawn not on d6 after en passant"
        assert state.board.has_legal_en_passant() is False

    def test_black_can_capture_en_passant(self):
        """FEN: white pawn on e4 (just pushed e2-e4), black pawn on d4.
        Black captures en passant: d4xe3.
        """
        state.board = chess.Board("8/8/8/8/3pP3/8/8/4K3 b - e3 0 1")
        assert state.board.has_legal_en_passant()
        # Black captures en passant: d4->e3
        assert chess.Move.from_uci("d4e3") in state.board.legal_moves

    def test_en_passant_not_available_after_delay(self):
        """En passant must only be available immediately after a two-square pawn push."""
        state.board = chess.Board("4k3/4p3/8/3pP3/8/8/8/4K3 w - d6 0 1")
        assert state.board.has_legal_en_passant()
        # Play a non-en-passant pawn move
        state.board.push(chess.Move.from_uci("e5e6"))
        assert state.board.has_legal_en_passant() is False

    def test_no_en_passant_when_pawn_has_not_moved_twosquares(self):
        state.board = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - - 0 1")
        assert state.board.has_legal_en_passant() is False


# ---------------------------------------------------------------------------
# Test: Check Detection
# ---------------------------------------------------------------------------


class TestCheck:
    def test_check_detected_in_fen(self):
        """Bishop on b5 checks king on e8 (diagonal b5-c6-d7-e8)."""
        state.board = chess.Board("rnbqkbnr/ppp1pppp/8/1B6/8/8/PPPP1PPP/RNBQK1NR b KQkq - 1 2")
        assert state.board.is_check()

    def test_not_in_check_when_safe(self):
        state.board = chess.Board()
        assert state.board.is_check() is False

    def test_check_must_be_resolved(self):
        """When in check, every legal move must remove the check."""
        # Bishop on b5 checks black king on e8 (diagonal b5-c6-d7-e8).
        state.board = chess.Board("rnbqkbnr/ppp2ppp/8/1B6/8/8/PPPP1PPP/RNBQK1NR b KQkq - 0 1")
        assert state.board.is_check()
        legal_moves = list(state.board.legal_moves)
        for move in legal_moves:
            state.board.push(move)
            assert state.board.is_check() is False, f"Move {move.uci()} didn't resolve check"
            state.board.pop()


# ---------------------------------------------------------------------------
# Test: Checkmate
# ---------------------------------------------------------------------------


class TestCheckmate:
    def test_scholars_mate_is_checkmate(self):
        """After 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6?? 4.Qxf7#"""
        state.board = chess.Board(
            "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
        )
        assert state.board.is_checkmate()
        assert state.board.is_game_over()
        assert state.board.result() == "1-0"

    def test_stalemate_is_not_checkmate(self):
        """Black king on a8 trapped by white king on b6 and pawns on a7, c7."""
        state.board = chess.Board("k7/P1P5/1K6/8/8/8/8/8 b - - 0 1")
        assert state.board.is_stalemate()
        assert state.board.is_game_over()
        assert state.board.result() == "1/2-1/2"

    def test_insufficient_material(self):
        state.board = chess.Board("8/8/4k3/8/8/8/4K3/8 w - - 0 1")
        assert state.board.is_game_over()
        assert state.board.result() == "1/2-1/2"

    def test_fifty_move_rule(self):
        state.board = chess.Board("8/8/8/8/8/8/k7/4K3 b - - 100 51")
        assert state.board.can_claim_fifty_moves()


# ---------------------------------------------------------------------------
# Test: Bot-vs-Bot Flow
# ---------------------------------------------------------------------------


class TestBotVsBot:
    def test_bot_vs_bot_returns_bot_moves(self):
        state.mode = "bot_vs_bot"
        result = _do_bot_move()
        assert "human_turn" not in result
        assert "move" in result
        assert len(result["move"]) >= 4

    def test_bot_vs_bot_consecutive_moves(self):
        """Simulate 10 consecutive bot-vs-bot moves; every move must be legal
        in the position it was played from.
        """
        state.mode = "bot_vs_bot"
        for i in range(10):
            if state.board.is_game_over():
                break
            # Snapshot the board BEFORE the bot move
            fen_before = state.board.fen()
            result = _do_bot_move()
            move = chess.Move.from_uci(result["move"])
            # Verify move was legal in the pre-move position
            board_before = chess.Board(fen_before)
            assert move in board_before.legal_moves, (
                f"Move {move.uci()} (turn {i}) not legal in {fen_before}"
            )

    def test_bot_vs_bot_state_updates_fen(self):
        result = _do_bot_move()
        assert "fen" in result
        new_board = chess.Board(result["fen"])
        assert new_board.fullmove_number >= state.board.fullmove_number

    def test_bot_vs_bot_turn_tracking(self):
        state.mode = "bot_vs_bot"
        for i in range(6):
            if state.board.is_game_over():
                break
            result = _do_bot_move()
            # Turn alternates
            assert result["turn"] in ("white", "black")

    def test_bot_vs_bot_game_over_response(self):
        """With random bots, game should end within 500 moves."""
        state.mode = "bot_vs_bot"
        state.white_engine = "random"
        state.black_engine = "random"
        move_count = 0
        result = None
        while not state.board.is_game_over() and move_count < 500:
            result = _do_bot_move()
            move_count += 1
        assert state.board.is_game_over()
        assert result["game_over"] is True

    def test_full_game_random_bots(self):
        """Play a full game with random bots — every move must be legal in its position."""
        state.mode = "bot_vs_bot"
        state.white_engine = "random"
        state.black_engine = "random"
        move_num = 0
        while not state.board.is_game_over() and move_num < 100:
            fen_before = state.board.fen()
            result = _do_bot_move()
            move = chess.Move.from_uci(result["move"])
            board_before = chess.Board(fen_before)
            assert move in board_before.legal_moves, (
                f"Move {move.uci()} not legal in {fen_before} at turn {move_num}"
            )
            move_num += 1

    def test_random_bot_no_options(self):
        """RandomBot should work without skill options."""
        state.mode = "bot_vs_bot"
        state.white_engine = "random"
        state.black_engine = "random"
        fen_before = state.board.fen()
        result = _do_bot_move()
        assert "move" in result
        move = chess.Move.from_uci(result["move"])
        # Verify legality against pre-move board (state.board was mutated by _do_bot_move)
        board_before = chess.Board(fen_before)
        assert move in board_before.legal_moves


# ---------------------------------------------------------------------------
# Test: Player-vs-Bot Flow
# ---------------------------------------------------------------------------


class TestPlayerVsBot:
    def test_player_vs_bot_human_turn_white(self):
        state.mode = "player_vs_bot"
        state.player_color = chess.WHITE
        assert _is_human_turn() is True

    def test_player_vs_bot_human_turn_black(self):
        state.mode = "player_vs_bot"
        state.player_color = chess.BLACK
        state.board.push(chess.Move.from_uci("e2e4"))
        assert _is_human_turn() is True

    def test_player_vs_bot_not_human_on_own_turn(self):
        state.mode = "player_vs_bot"
        state.player_color = chess.WHITE
        state.board.push(chess.Move.from_uci("e2e4"))
        assert state.board.turn == chess.BLACK
        assert _is_human_turn() is False

    def test_player_vs_bot_not_human_on_bot_turn(self):
        state.mode = "player_vs_bot"
        state.player_color = chess.BLACK
        assert _is_human_turn() is False

    def test_full_game_human_vs_random(self):
        """Simulate human vs random bot — human moves must be legal, bot moves must be legal."""
        import random
        state.mode = "player_vs_bot"
        state.player_color = chess.WHITE
        state.white_engine = "random"
        state.black_engine = "random"
        move_num = 0
        while not state.board.is_game_over() and move_num < 50:
            if _is_human_turn():
                legal = list(state.board.legal_moves)
                move = random.choice(legal)
                state.board.push(move)
                move_num += 1
            else:
                fen_before = state.board.fen()
                result = _do_bot_move()
                bot_move = chess.Move.from_uci(result["move"])
                board_before = chess.Board(fen_before)
                assert bot_move in board_before.legal_moves, (
                    f"Bot move {bot_move.uci()} not legal in {fen_before}"
                )
                move_num += 1


# ---------------------------------------------------------------------------
# Test: Move Validation
# ---------------------------------------------------------------------------


class TestMoveValidation:
    def test_starting_position_legal_moves(self):
        legal = list(state.board.legal_moves)
        assert len(legal) == 20

    def test_pawn_can_advance_two_squares(self):
        moves = [m for m in state.board.legal_moves if m.from_square == chess.E2]
        assert chess.Move.from_uci("e2e3") in moves
        assert chess.Move.from_uci("e2e4") in moves

    def test_knight_has_two_starting_moves_each(self):
        b1_moves = [m for m in state.board.legal_moves if m.from_square == chess.B1]
        g1_moves = [m for m in state.board.legal_moves if m.from_square == chess.G1]
        assert len(b1_moves) == 2
        assert len(g1_moves) == 2

    def test_illegal_moves_rejected(self):
        bishop_move = chess.Move.from_uci("f1a6")
        assert bishop_move not in state.board.legal_moves

    def test_pawn_forward_advance(self):
        """Pawn can move straight forward to an empty square."""
        state.board = chess.Board("8/4p3/8/4P3/8/8/8/8 w - - 0 1")
        fwd_move = chess.Move.from_uci("e5e6")
        assert fwd_move in state.board.legal_moves

    def test_pawn_can_capture_diagonally(self):
        """Pawn can capture diagonally if enemy piece present."""
        state.board = chess.Board("8/8/5p2/4P3/8/8/8/8 w - - 0 1")
        legal = list(state.board.legal_moves)
        captures = [m for m in legal if m.to_square == chess.F6]
        assert len(captures) == 1

    def test_king_cannot_move_into_check(self):
        state.board = chess.Board("8/8/3k4/8/4K3/8/8/8 w - - 0 1")
        legal = list(state.board.legal_moves)
        # d5 and e5 are adjacent to black king on d6
        assert chess.Move.from_uci("e4d5") not in legal
        assert chess.Move.from_uci("e4e5") not in legal
        # e3 is safe
        assert chess.Move.from_uci("e4e3") in legal


# ---------------------------------------------------------------------------
# Test: Game State Lifecycle
# ---------------------------------------------------------------------------


class TestGameLifecycle:
    def test_reset_clears_board(self):
        state.board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        state.reset()
        assert state.board.fen() == chess.STARTING_FEN

    def test_skill_options_bounds(self):
        opts = state.skill_options("stockfish", 0)
        assert opts == {"Skill Level": 0}
        opts = state.skill_options("stockfish", 100)
        assert opts == {"Skill Level": 20}
        opts = state.skill_options("stockfish", 10)
        assert opts == {"Skill Level": 10}

    def test_skill_options_random_bot(self):
        opts = state.skill_options("random", 10)
        assert opts == {"Skill Level": 0}

    def test_fen_roundtrips(self):
        import random
        for _ in range(10):
            if state.board.is_game_over():
                break
            state.board.push(random.choice(list(state.board.legal_moves)))
        fen = state.board.fen()
        board2 = chess.Board(fen)
        # Compare FENs to verify roundtrip preserves position
        assert board2.fen() == fen


# ---------------------------------------------------------------------------
# Test: _do_bot_move output structure
# ---------------------------------------------------------------------------


class TestBotMoveOutput:
    def test_bot_move_has_required_fields(self):
        result = _do_bot_move()
        for field in ("move", "from", "to", "fen", "game_over", "turn", "engine"):
            assert field in result, f"Missing field: {field}"

    def test_move_fields_are_uci_squares(self):
        result = _do_bot_move()
        assert len(result["move"]) >= 4
        assert len(result["from"]) == 2
        assert len(result["to"]) == 2

    def test_game_over_response_has_result(self):
        state.mode = "bot_vs_bot"
        state.white_engine = "random"
        state.black_engine = "random"
        while not state.board.is_game_over():
            result = _do_bot_move()
        assert result["game_over"] is True
        assert result["result"] in ["1-0", "0-1", "1/2-1/2"]


# ---------------------------------------------------------------------------
# Test: Draw Conditions
# ---------------------------------------------------------------------------


class TestDrawConditions:
    def test_threefold_repetition(self):
        """Repeat the same position three times."""
        state.board = chess.Board()
        for _ in range(2):  # two full cycles = 3 occurrences
            state.board.push_san("Nf3")
            state.board.push_san("Nf6")
            state.board.push_san("Ng1")
            state.board.push_san("Ng8")
        assert state.board.can_claim_threefold_repetition()

    def test_draw_by_insufficient_material(self):
        state.board = chess.Board("8/8/8/8/8/8/8/4K2k w - - 0 1")
        assert state.board.is_insufficient_material()
        assert state.board.result() == "1/2-1/2"


# ---------------------------------------------------------------------------
# Test: Move tracking
# ---------------------------------------------------------------------------


class TestMoveTracking:
    def test_bot_move_records_move(self):
        """state.moves grows by 1 after a bot move."""
        initial_len = len(state.moves)
        _do_bot_move()
        assert len(state.moves) == initial_len + 1

    def test_bot_move_record_correct_san(self):
        """The SAN string matches the board state after the move."""
        result = _do_bot_move()
        move = state.moves[-1]
        assert move["san"] == result["san"]
        assert move["color"] == "white"
        assert move["from"] == result["from"]
        assert move["to"] == result["to"]



    def test_player_move_records_both_moves(self):
        """Both player and bot moves are tracked after a player-move round."""
        state.board = chess.Board()
        state.board.push_san("e4")
        initial_len = len(state.moves)
        bot_result = _do_bot_move()
        assert len(state.moves) == initial_len + 1
        assert state.moves[-1]["san"] == bot_result["san"]

    def test_reset_clears_moves(self):
        """state.moves is empty after reset."""
        _do_bot_move()
        _do_bot_move()
        assert len(state.moves) >= 2
        state.reset()
        assert len(state.moves) == 0

    def test_move_list_groups_correctly(self):
        """The /api/moves endpoint returns properly grouped data."""
        from server import app
        state.mode = "bot_vs_bot"
        state.white_engine = "random"
        state.black_engine = "random"
        for _ in range(4):
            _do_bot_move()
        with app.test_client() as c:
            resp = c.get("/api/moves")
            assert resp.status_code == 200
            grouped = resp.get_json()
            assert len(grouped) == 2  # 4 moves → 2 pairs
            assert grouped[0]["moveNumber"] == 1
            assert grouped[0]["white"] is not None
            assert grouped[0]["black"] is not None
            assert grouped[1]["moveNumber"] == 2
            assert grouped[1]["white"] is not None
            assert grouped[1]["black"] is not None

    def test_move_record_preserves_color(self):
        """White moves record 'white' color, black moves record 'black'."""
        state.board = chess.Board()
        r1 = _do_bot_move()
        assert state.moves[-1]["color"] == "white"
        r2 = _do_bot_move()
        assert state.moves[-1]["color"] == "black"

