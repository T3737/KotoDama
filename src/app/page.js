"use client";

import { useEffect, useRef, useState } from "react";

export default function Home() {
  const canvasRef = useRef(null);

  const [health, setHealth] = useState(5);
  const [doubleJumpUnlocked, setDoubleJumpUnlocked] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");

    canvas.width = 1200;
    canvas.height = 700;

    const gravity = 0.7;

    const keys = {};

    const player = {
      x: 100,
      y: 100,
      width: 40,
      height: 50,
      velX: 0,
      velY: 0,
      speed: 5,
      jumpPower: -14,
      grounded: false,
      facing: 1,
      attacking: false,
      jumps: 0,
    };

    const camera = {
      x: 0,
    };

    const platforms = [
      { x: 0, y: 650, width: 2200, height: 50 },
      { x: 300, y: 520, width: 200, height: 20 },
      { x: 650, y: 430, width: 200, height: 20 },
      { x: 1050, y: 330, width: 200, height: 20 },
      { x: 1450, y: 500, width: 250, height: 20 },
    ];

    const enemies = [
      {
        x: 900,
        y: 610,
        width: 40,
        height: 40,
        dir: 1,
        alive: true,
      },
    ];

    const upgrade = {
      x: 1120,
      y: 280,
      width: 30,
      height: 30,
      collected: false,
    };

    const lockedGate = {
      x: 1700,
      y: 500,
      width: 60,
      height: 150,
    };

    function rectsCollide(a, b) {
      return (
        a.x < b.x + b.width &&
        a.x + a.width > b.x &&
        a.y < b.y + b.height &&
        a.y + a.height > b.y
      );
    }

    function attackEnemy() {
      enemies.forEach((enemy) => {
        if (!enemy.alive) return;

        const swordHitbox = {
          x: player.facing === 1 ? player.x + player.width : player.x - 40,
          y: player.y + 10,
          width: 40,
          height: 20,
        };

        if (rectsCollide(swordHitbox, enemy)) {
          enemy.alive = false;
        }
      });
    }

    function update() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      player.velX = 0;

      if (keys["a"] || keys["ArrowLeft"]) {
        player.velX = -player.speed;
        player.facing = -1;
      }

      if (keys["d"] || keys["ArrowRight"]) {
        player.velX = player.speed;
        player.facing = 1;
      }

      player.x += player.velX;

      player.velY += gravity;
      player.y += player.velY;

      player.grounded = false;

      platforms.forEach((platform) => {
        if (
          player.x < platform.x + platform.width &&
          player.x + player.width > platform.x &&
          player.y + player.height < platform.y + 20 &&
          player.y + player.height + player.velY >= platform.y
        ) {
          player.y = platform.y - player.height;
          player.velY = 0;
          player.grounded = true;
          player.jumps = 0;
        }
      });

      if (
        rectsCollide(player, lockedGate) &&
        !doubleJumpUnlocked
      ) {
        player.x -= player.velX;
      }

      enemies.forEach((enemy) => {
        if (!enemy.alive) return;

        enemy.x += enemy.dir * 2;

        if (enemy.x > 1050 || enemy.x < 750) {
          enemy.dir *= -1;
        }

        if (rectsCollide(player, enemy)) {
          setHealth((prev) => Math.max(prev - 1, 0));

          if (player.x < enemy.x) {
            player.x -= 40;
          } else {
            player.x += 40;
          }
        }
      });

      if (
        rectsCollide(player, upgrade) &&
        !upgrade.collected
      ) {
        upgrade.collected = true;
        setDoubleJumpUnlocked(true);
      }

      camera.x = player.x - 300;

      ctx.save();
      ctx.translate(-camera.x, 0);

      ctx.fillStyle = "#202020";
      ctx.fillRect(0, 0, 2400, 700);

      ctx.fillStyle = "#444";
      platforms.forEach((platform) => {
        ctx.fillRect(
          platform.x,
          platform.y,
          platform.width,
          platform.height
        );
      });

      ctx.fillStyle = "purple";
      ctx.fillRect(player.x, player.y, player.width, player.height);

      if (player.attacking) {
        ctx.fillStyle = "yellow";

        const swordX =
          player.facing === 1
            ? player.x + player.width
            : player.x - 40;

        ctx.fillRect(swordX, player.y + 10, 40, 20);
      }

      enemies.forEach((enemy) => {
        if (!enemy.alive) return;

        ctx.fillStyle = "red";
        ctx.fillRect(enemy.x, enemy.y, enemy.width, enemy.height);
      });

      if (!upgrade.collected) {
        ctx.fillStyle = "cyan";
        ctx.fillRect(
          upgrade.x,
          upgrade.y,
          upgrade.width,
          upgrade.height
        );
      }

      ctx.fillStyle = doubleJumpUnlocked
        ? "green"
        : "darkred";

      ctx.fillRect(
        lockedGate.x,
        lockedGate.y,
        lockedGate.width,
        lockedGate.height
      );

      ctx.restore();

      ctx.fillStyle = "white";
      ctx.font = "24px Arial";
      ctx.fillText(`Health: ${health}`, 20, 40);

      ctx.fillText(
        `Double Jump: ${doubleJumpUnlocked ? "Unlocked" : "Locked"}`,
        20,
        80
      );

      requestAnimationFrame(update);
    }

    function keyDown(e) {
      keys[e.key] = true;

      if (
        (e.key === "w" || e.key === "ArrowUp" || e.key === " ")
      ) {
        const maxJumps = doubleJumpUnlocked ? 2 : 1;

        if (player.jumps < maxJumps) {
          player.velY = player.jumpPower;
          player.jumps++;
        }
      }

      if (e.key === "j") {
        player.attacking = true;
        attackEnemy();

        setTimeout(() => {
          player.attacking = false;
        }, 120);
      }
    }

    function keyUp(e) {
      keys[e.key] = false;
    }

    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);

    update();

    return () => {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
    };
  }, [doubleJumpUnlocked, health]);

  return (
    <main className="w-screen h-screen bg-black flex items-center justify-center overflow-hidden">
      <canvas
        ref={canvasRef}
        className="border border-zinc-700 rounded-xl"
      />
    </main>
  );
}