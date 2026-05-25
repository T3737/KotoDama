"use client";

import { useEffect, useRef, useState } from "react";

export default function Home() {
  const canvasRef = useRef(null);
  const healthRef = useRef(5);
  const doubleJumpRef = useRef(false);
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
      invincible: 0,
    };

    const camera = { x: 0 };

    const platforms = [
      { x: 0, y: 650, width: 2200, height: 50 },
      { x: 300, y: 520, width: 200, height: 20 },
      { x: 650, y: 430, width: 200, height: 20 },
      { x: 1050, y: 330, width: 200, height: 20 },
      { x: 1450, y: 500, width: 250, height: 20 },
    ];

    const enemies = [
      { x: 900, y: 610, width: 40, height: 40, dir: 1, alive: true },
    ];

    const upgrade = { x: 1120, y: 280, width: 30, height: 30, collected: false };

    const lockedGate = { x: 1700, y: 500, width: 60, height: 150 };

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

    let animId;

    function update() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // --- INPUT ---
      player.velX = 0;
      if (keys["a"] || keys["ArrowLeft"]) { player.velX = -player.speed; player.facing = -1; }
      if (keys["d"] || keys["ArrowRight"]) { player.velX = player.speed; player.facing = 1; }

      // --- HORIZONTAL MOVE ---
      player.x += player.velX;

      // horizontal platform collision
      platforms.forEach((p) => {
        if (rectsCollide(player, p)) {
          if (player.velX > 0) player.x = p.x - player.width;
          else if (player.velX < 0) player.x = p.x + p.width;
        }
      });

      // --- VERTICAL MOVE ---
      player.velY += gravity;
      player.y += player.velY;
      player.grounded = false;

      platforms.forEach((p) => {
        if (
          player.x < p.x + p.width &&
          player.x + player.width > p.x &&
          player.y + player.height >= p.y &&
          player.y + player.height <= p.y + p.height + Math.abs(player.velY) + 1
        ) {
          if (player.velY >= 0) {
            player.y = p.y - player.height;
            player.velY = 0;
            player.grounded = true;
            player.jumps = 0;
          }
        }
        // ceiling
        if (
          player.x < p.x + p.width &&
          player.x + player.width > p.x &&
          player.y <= p.y + p.height &&
          player.y >= p.y &&
          player.velY < 0
        ) {
          player.y = p.y + p.height;
          player.velY = 0;
        }
      });

      // gate block if not unlocked
      if (rectsCollide(player, lockedGate) && !doubleJumpRef.current) {
        player.x -= player.velX;
        if (player.velX === 0) player.x = lockedGate.x - player.width;
      }

      // --- ENEMIES ---
      enemies.forEach((enemy) => {
        if (!enemy.alive) return;
        enemy.x += enemy.dir * 2;
        if (enemy.x > 1050 || enemy.x < 750) enemy.dir *= -1;

        if (rectsCollide(player, enemy) && player.invincible <= 0) {
          const newHealth = Math.max(healthRef.current - 1, 0);
          healthRef.current = newHealth;
          setHealth(newHealth);
          player.invincible = 60;
          player.x += player.facing * -40;
          player.velY = -6;
        }
      });

      if (player.invincible > 0) player.invincible--;

      // --- UPGRADE ---
      if (rectsCollide(player, upgrade) && !upgrade.collected) {
        upgrade.collected = true;
        doubleJumpRef.current = true;
        setDoubleJumpUnlocked(true);
      }

      // --- CAMERA ---
      camera.x = Math.max(0, player.x - 300);

      // --- DRAW ---
      ctx.save();
      ctx.translate(-camera.x, 0);

      // ============================================================
      // SPRITES: replace fillRect calls below with ctx.drawImage()
      // Example: ctx.drawImage(mySprite, x, y, width, height)
      // Load sprites above useEffect or inside it with new Image()
      // ============================================================

      // BACKGROUND sprite goes here (currently solid color)
      ctx.fillStyle = "#202020";
      ctx.fillRect(camera.x, 0, canvas.width, canvas.height);

      // PLATFORM sprite goes here
      ctx.fillStyle = "#444";
      platforms.forEach((p) => ctx.fillRect(p.x, p.y, p.width, p.height));

      // GATE sprite goes here
      ctx.fillStyle = doubleJumpRef.current ? "green" : "darkred";
      ctx.fillRect(lockedGate.x, lockedGate.y, lockedGate.width, lockedGate.height);

      // UPGRADE/POWERUP sprite goes here
      if (!upgrade.collected) {
        ctx.fillStyle = "cyan";
        ctx.fillRect(upgrade.x, upgrade.y, upgrade.width, upgrade.height);
      }

      // ENEMY sprite goes here
      enemies.forEach((enemy) => {
        if (!enemy.alive) return;
        ctx.fillStyle = "red";
        ctx.fillRect(enemy.x, enemy.y, enemy.width, enemy.height);
      });

      // PLAYER sprite goes here (flashes when invincible)
      if (player.invincible <= 0 || Math.floor(player.invincible / 5) % 2 === 0) {
        ctx.fillStyle = "purple";
        ctx.fillRect(player.x, player.y, player.width, player.height);
      }

      // SWORD sprite goes here
      if (player.attacking) {
        ctx.fillStyle = "yellow";
        const swordX = player.facing === 1 ? player.x + player.width : player.x - 40;
        ctx.fillRect(swordX, player.y + 10, 40, 20);
      }

      ctx.restore();

      // HUD (drawn after ctx.restore so not affected by camera translate)
      ctx.fillStyle = "white";
      ctx.font = "24px Arial";
      ctx.fillText(`Health: ${healthRef.current}`, 20, 40);
      ctx.fillText(`Double Jump: ${doubleJumpRef.current ? "Unlocked" : "Locked"}`, 20, 80);

      animId = requestAnimationFrame(update);
    }

    function keyDown(e) {
      keys[e.key] = true;
      if (e.key === "w" || e.key === "ArrowUp" || e.key === " ") {
        const maxJumps = doubleJumpRef.current ? 2 : 1;
        if (player.jumps < maxJumps) {
          player.velY = player.jumpPower;
          player.jumps++;
        }
      }
      if (e.key === "j") {
        player.attacking = true;
        attackEnemy();
        setTimeout(() => { player.attacking = false; }, 120);
      }
    }

    function keyUp(e) { keys[e.key] = false; }

    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    update();

    return () => {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      cancelAnimationFrame(animId);
    };
  }, []); // empty deps - game loop never restarts

  return (
    <main className="w-screen h-screen bg-black flex items-center justify-center overflow-hidden">
      <canvas ref={canvasRef} className="border border-zinc-700 rounded-xl" />
    </main>
  );
}