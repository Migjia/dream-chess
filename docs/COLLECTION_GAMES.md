# Data collection: three scripted games

62 demos in three games (31, 20 and 11): 23 with the left arm, 39 with the right, including 15 capture steps, 0 castling steps and 6 fix demos. White's moves are human-style openings; Brown's replies and every task text come from the app's own code, so each demo is exactly what the app would ask Dream-1 in a real game.

The robot plays Brown, from the side nearest the arms (rank 8 closest, the h-file at the robot's left).

## For the White player

- Before each game, set up the normal starting position with brown nearest the robot.
- When a line says `WHITE: play ...`, move that white piece by hand. It's not recorded.
- Then wait for the collector to finish every demo under it before your next move.
- If something on the board goes wrong, stop and put the position back as it should be.

## For the data collector (Quest teleop)

Before the first game, home the arms with the station, then start `dhk-collect`. Its start pose is then the pose the
robot starts every move from in a real game. Between demos, click the right joystick to return to it.

For every `DEMO` line:

1. Copy the line under it **exactly** into the dashboard's task box and press **Set task**. Check it took.
2. Start with both arms still at the start pose, then press **A** to record.
3. Do the move with **the arm named in brackets**, even if the other would be easier. Leave the other arm still.
4. Return to the start pose, then press **A** to save. If it went wrong, press **B** and redo it.

Agree on one technique before starting, and everyone uses it: approach straight down, grasp the piece at the same
height, lift above the kings before crossing the board, set it down centered and upright, then lift straight up. The
variety should come from the positions, not from different ways of moving.

A capture is two demos: first the white piece into the tray beside that arm, then the brown piece onto its square. A fix demo starts with a piece nudged out of place by hand, and says only "brown piece", because that's how the app words its fixes.

Take turns between games. Note the number of any bad episode as you go (for example "#14: knocked the pawn"), then
clean the data afterward: delete any episode that grabbed two pieces, knocked a piece over, used the wrong square or
the wrong arm.

These replies come from the app's built-in engine, which is what the NUC uses today. If Stockfish gets installed, the app will choose different moves, but the prompts follow exactly the same pattern, so the data stays valid.

## Game 1

```text
WHITE: play e4  (e2 to e4)
  DEMO 1  [LEFT arm]  Brown Nf6
  Using your left arm, pick up the brown knight on square g8 and place it upright in the center of square f6. Move slowly and do not touch any other piece.

WHITE: play Nf3  (g1 to f3)
  DEMO 2  [LEFT arm]  Brown Nxe4, step 1 of 2
  Using your left arm, pick up the white pawn on square e4 and put it in the tray on your left. Move slowly and do not touch any other piece.
  DEMO 3  [LEFT arm]  Brown Nxe4, step 2 of 2
  Using your left arm, pick up the brown knight on square f6 and place it upright in the center of square e4. Move slowly and do not touch any other piece.

WHITE: play Bc4  (f1 to c4)
  DEMO 4  [RIGHT arm]  Brown Nc6
  Using your right arm, pick up the brown knight on square b8 and place it upright in the center of square c6. Move slowly and do not touch any other piece.

WHITE: play d3  (d2 to d3)
  DEMO 5  [LEFT arm]  Brown Nc5
  Using your left arm, pick up the brown knight on square e4 and place it upright in the center of square c5. Move slowly and do not touch any other piece.

WHITE: play O-O  (e1 to g1)
  DEMO 6  [RIGHT arm]  Brown d5
  Using your right arm, pick up the brown pawn on square d7 and place it upright in the center of square d5. Move slowly and do not touch any other piece.

WHITE: play c3  (c2 to c3)
  DEMO 7  [RIGHT arm]  Brown dxc4, step 1 of 2
  Using your right arm, pick up the white bishop on square c4 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 8  [RIGHT arm]  Brown dxc4, step 2 of 2
  Using your right arm, pick up the brown pawn on square d5 and place it upright in the center of square c4. Move slowly and do not touch any other piece.
  DEMO 9  [RIGHT arm]  Fix: first nudge the brown piece on c4 by hand onto b3
  Using your right arm, pick up the brown piece on square b3 and place it upright in the center of square c4. Move slowly and do not touch any other piece.

WHITE: play Nbd2  (b1 to d2)
  DEMO 10  [RIGHT arm]  Brown Qxd3, step 1 of 2
  Using your right arm, pick up the white pawn on square d3 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 11  [RIGHT arm]  Brown Qxd3, step 2 of 2
  Using your right arm, pick up the brown queen on square d8 and place it upright in the center of square d3. Move slowly and do not touch any other piece.

WHITE: play h3  (h2 to h3)
  DEMO 12  [LEFT arm]  Brown e5
  Using your left arm, pick up the brown pawn on square e7 and place it upright in the center of square e5. Move slowly and do not touch any other piece.

WHITE: play Nxe5  (f3 to e5)
  DEMO 13  [LEFT arm]  Brown Nxe5, step 1 of 2
  Using your left arm, pick up the white knight on square e5 and put it in the tray on your left. Move slowly and do not touch any other piece.
  DEMO 14  [RIGHT arm]  Brown Nxe5, step 2 of 2
  Using your right arm, pick up the brown knight on square c6 and place it upright in the center of square e5. Move slowly and do not touch any other piece.

WHITE: play Re1  (f1 to e1)
  DEMO 15  [LEFT arm]  Brown Bd6
  Using your left arm, pick up the brown bishop on square f8 and place it upright in the center of square d6. Move slowly and do not touch any other piece.

WHITE: play f3  (f2 to f3)
  DEMO 16  [RIGHT arm]  Brown Bf5
  Using your right arm, pick up the brown bishop on square c8 and place it upright in the center of square f5. Move slowly and do not touch any other piece.

WHITE: play Rxe5+  (e1 to e5)
  DEMO 17  [LEFT arm]  Brown Bxe5, step 1 of 2
  Using your left arm, pick up the white rook on square e5 and put it in the tray on your left. Move slowly and do not touch any other piece.
  DEMO 18  [RIGHT arm]  Brown Bxe5, step 2 of 2
  Using your right arm, pick up the brown bishop on square d6 and place it upright in the center of square e5. Move slowly and do not touch any other piece.
  DEMO 19  [LEFT arm]  Fix: first nudge the brown piece on e5 by hand onto e6
  Using your left arm, pick up the brown piece on square e6 and place it upright in the center of square e5. Move slowly and do not touch any other piece.

WHITE: play Kf2  (g1 to f2)
  DEMO 20  [RIGHT arm]  Brown c6
  Using your right arm, pick up the brown pawn on square c7 and place it upright in the center of square c6. Move slowly and do not touch any other piece.

WHITE: play a3  (a2 to a3)
  DEMO 21  [LEFT arm]  Brown f6
  Using your left arm, pick up the brown pawn on square f7 and place it upright in the center of square f6. Move slowly and do not touch any other piece.

WHITE: play Ra2  (a1 to a2)
  DEMO 22  [LEFT arm]  Brown Kd7
  Using your left arm, pick up the brown king on square e8 and place it upright in the center of square d7. Move slowly and do not touch any other piece.

WHITE: play b3  (b2 to b3)
  DEMO 23  [RIGHT arm]  Brown Nxb3, step 1 of 2
  Using your right arm, pick up the white pawn on square b3 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 24  [RIGHT arm]  Brown Nxb3, step 2 of 2
  Using your right arm, pick up the brown knight on square c5 and place it upright in the center of square b3. Move slowly and do not touch any other piece.

WHITE: play Bb2  (c1 to b2)
  DEMO 25  [RIGHT arm]  Brown Nxd2, step 1 of 2
  Using your right arm, pick up the white knight on square d2 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 26  [RIGHT arm]  Brown Nxd2, step 2 of 2
  Using your right arm, pick up the brown knight on square b3 and place it upright in the center of square d2. Move slowly and do not touch any other piece.

WHITE: play a4  (a3 to a4)
  DEMO 27  [RIGHT arm]  Brown Ne4+
  Using your right arm, pick up the brown knight on square d2 and place it upright in the center of square e4. Move slowly and do not touch any other piece.
  DEMO 28  [RIGHT arm]  Fix: first nudge the brown piece on e4 by hand onto d4
  Using your right arm, pick up the brown piece on square d4 and place it upright in the center of square e4. Move slowly and do not touch any other piece.

WHITE: play fxe4  (f3 to e4)
  DEMO 29  [LEFT arm]  Brown Bg3+
  Using your left arm, pick up the brown bishop on square e5 and place it upright in the center of square g3. Move slowly and do not touch any other piece.

WHITE: play Kg1  (f2 to g1)
  DEMO 30  [RIGHT arm]  Brown Qxd1#, step 1 of 2
  Using your right arm, pick up the white queen on square d1 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 31  [RIGHT arm]  Brown Qxd1#, step 2 of 2
  Using your right arm, pick up the brown queen on square d3 and place it upright in the center of square d1. Move slowly and do not touch any other piece.

```

## Game 2

```text
WHITE: play d4  (d2 to d4)
  DEMO 1  [RIGHT arm]  Brown Nc6
  Using your right arm, pick up the brown knight on square b8 and place it upright in the center of square c6. Move slowly and do not touch any other piece.

WHITE: play c4  (c2 to c4)
  DEMO 2  [LEFT arm]  Brown Nf6
  Using your left arm, pick up the brown knight on square g8 and place it upright in the center of square f6. Move slowly and do not touch any other piece.

WHITE: play Nc3  (b1 to c3)
  DEMO 3  [LEFT arm]  Brown e6
  Using your left arm, pick up the brown pawn on square e7 and place it upright in the center of square e6. Move slowly and do not touch any other piece.

WHITE: play Nf3  (g1 to f3)
  DEMO 4  [LEFT arm]  Brown Bb4
  Using your left arm, pick up the brown bishop on square f8 and place it upright in the center of square b4. Move slowly and do not touch any other piece.

WHITE: play Bg5  (c1 to g5)
  DEMO 5  [RIGHT arm]  Brown Bxc3+, step 1 of 2
  Using your right arm, pick up the white knight on square c3 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 6  [RIGHT arm]  Brown Bxc3+, step 2 of 2
  Using your right arm, pick up the brown bishop on square b4 and place it upright in the center of square c3. Move slowly and do not touch any other piece.

WHITE: play Bd2  (g5 to d2)
  DEMO 7  [RIGHT arm]  Brown Bxb2, step 1 of 2
  Using your right arm, pick up the white pawn on square b2 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 8  [RIGHT arm]  Brown Bxb2, step 2 of 2
  Using your right arm, pick up the brown bishop on square c3 and place it upright in the center of square b2. Move slowly and do not touch any other piece.
  DEMO 9  [RIGHT arm]  Fix: first nudge the brown piece on b2 by hand onto c1
  Using your right arm, pick up the brown piece on square c1 and place it upright in the center of square b2. Move slowly and do not touch any other piece.

WHITE: play Rb1  (a1 to b1)
  DEMO 10  [RIGHT arm]  Brown Bxd4, step 1 of 2
  Using your right arm, pick up the white pawn on square d4 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 11  [RIGHT arm]  Brown Bxd4, step 2 of 2
  Using your right arm, pick up the brown bishop on square b2 and place it upright in the center of square d4. Move slowly and do not touch any other piece.

WHITE: play Nxd4  (f3 to d4)
  DEMO 12  [RIGHT arm]  Brown Nxd4, step 1 of 2
  Using your right arm, pick up the white knight on square d4 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 13  [RIGHT arm]  Brown Nxd4, step 2 of 2
  Using your right arm, pick up the brown knight on square c6 and place it upright in the center of square d4. Move slowly and do not touch any other piece.

WHITE: play Bc3  (d2 to c3)
  DEMO 14  [LEFT arm]  Brown e5
  Using your left arm, pick up the brown pawn on square e6 and place it upright in the center of square e5. Move slowly and do not touch any other piece.

WHITE: play e3  (e2 to e3)
  DEMO 15  [LEFT arm]  Brown Ne4
  Using your left arm, pick up the brown knight on square f6 and place it upright in the center of square e4. Move slowly and do not touch any other piece.

WHITE: play Bb2  (c3 to b2)
  DEMO 16  [RIGHT arm]  Brown Qh4
  Using your right arm, pick up the brown queen on square d8 and place it upright in the center of square h4. Move slowly and do not touch any other piece.

WHITE: play Qa4  (d1 to a4)
  DEMO 17  [LEFT arm]  Brown Qxf2+, step 1 of 2
  Using your left arm, pick up the white pawn on square f2 and put it in the tray on your left. Move slowly and do not touch any other piece.
  DEMO 18  [LEFT arm]  Brown Qxf2+, step 2 of 2
  Using your left arm, pick up the brown queen on square h4 and place it upright in the center of square f2. Move slowly and do not touch any other piece.
  DEMO 19  [LEFT arm]  Fix: first nudge the brown piece on f2 by hand onto e2
  Using your left arm, pick up the brown piece on square e2 and place it upright in the center of square f2. Move slowly and do not touch any other piece.

WHITE: play Kd1  (e1 to d1)
  DEMO 20  [LEFT arm]  Brown Qd2#
  Using your left arm, pick up the brown queen on square f2 and place it upright in the center of square d2. Move slowly and do not touch any other piece.

```

## Game 3

```text
WHITE: play c4  (c2 to c4)
  DEMO 1  [RIGHT arm]  Brown d5
  Using your right arm, pick up the brown pawn on square d7 and place it upright in the center of square d5. Move slowly and do not touch any other piece.

WHITE: play Nc3  (b1 to c3)
  DEMO 2  [RIGHT arm]  Brown dxc4, step 1 of 2
  Using your right arm, pick up the white pawn on square c4 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 3  [RIGHT arm]  Brown dxc4, step 2 of 2
  Using your right arm, pick up the brown pawn on square d5 and place it upright in the center of square c4. Move slowly and do not touch any other piece.

WHITE: play g3  (g2 to g3)
  DEMO 4  [RIGHT arm]  Brown Nc6
  Using your right arm, pick up the brown knight on square b8 and place it upright in the center of square c6. Move slowly and do not touch any other piece.

WHITE: play Bg2  (f1 to g2)
  DEMO 5  [RIGHT arm]  Brown Qd4
  Using your right arm, pick up the brown queen on square d8 and place it upright in the center of square d4. Move slowly and do not touch any other piece.

WHITE: play Nf3  (g1 to f3)
  DEMO 6  [RIGHT arm]  Brown Qf6
  Using your right arm, pick up the brown queen on square d4 and place it upright in the center of square f6. Move slowly and do not touch any other piece.

WHITE: play O-O  (e1 to g1)
  DEMO 7  [RIGHT arm]  Brown Bg4
  Using your right arm, pick up the brown bishop on square c8 and place it upright in the center of square g4. Move slowly and do not touch any other piece.
  DEMO 8  [LEFT arm]  Fix: first nudge the brown piece on g4 by hand onto f5
  Using your left arm, pick up the brown piece on square f5 and place it upright in the center of square g4. Move slowly and do not touch any other piece.

WHITE: play Nd5  (c3 to d5)
  DEMO 9  [LEFT arm]  Brown Qd6
  Using your left arm, pick up the brown queen on square f6 and place it upright in the center of square d6. Move slowly and do not touch any other piece.

WHITE: play d4  (d2 to d4)
  DEMO 10  [RIGHT arm]  Brown Qxd5, step 1 of 2
  Using your right arm, pick up the white knight on square d5 and put it in the tray on your right. Move slowly and do not touch any other piece.
  DEMO 11  [RIGHT arm]  Brown Qxd5, step 2 of 2
  Using your right arm, pick up the brown queen on square d6 and place it upright in the center of square d5. Move slowly and do not touch any other piece.

```
