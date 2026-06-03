import chess
import chess.engine
import os

STOCKFISH_PATH = os.path.abspath("./stockfish")

# Note: Stockfish's minimum ELO is ~1320. For "500 ELO" we use min skill.
# Skill Level 0 ≈ 1300 Elo, and we can't go lower in Stockfish.
# You could use a different engine like "Fairy-Stockfish" with handicaps for lower Elo.

engine_w = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
engine_b = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

# Set strengths
engine_w.configure({"Skill Level": 5})   # ~1500 Elo
engine_b.configure({"Skill Level": 0})   # ~1300 Elo (minimum)

board = chess.Board()
move_num = 1
history = []
draw_count = 0

print("=" * 50)
print("Stockfish (SL5 ~1500) vs Stockfish (SL0 ~1300)")
print("=" * 50)

while not board.is_game_over() and move_num <= 80:
    piece = "White" if board.turn == chess.WHITE else "Black"
    engine = engine_w if board.turn == chess.WHITE else engine_b
    strength = "SL5" if board.turn == chess.WHITE else "SL0"

    result = engine.play(board, chess.engine.Limit(time=1.0))
    board.push(result.move)
    history.append(result.move.uci())

    print(f"{move_num:3d}. {piece:6s} ({strength:4s})  {result.move.uci()}")
    move_num += 1

print(f"\nResult: {board.result()}")
print(f"Total moves: {len(history)}")
print(f"PGN: {' '.join(history[:20])}...")

engine_w.quit()
engine_b.quit()
