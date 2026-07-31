const readline = require('readline');

const createMenu = (prompt, options) => {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: true
  });

  let currentIndex = 0;
  const rows = options.length;
  let stdoutWrite = process.stdout.write;

  const render = () => {
    stdoutWrite(`\x1b[2J\x1b[0f${prompt}\n`);
    options.forEach((option, index) => {
      const prefix = index === currentIndex ? '❯ ' : '  ';
      stdoutWrite(`${prefix}${option}\n`);
    });
  };

  process.stdin.on('keypress', (ch, key) => {
    if (key.name === 'up' || key.name === 'w') {
      currentIndex = Math.max(0, currentIndex - 1);
      render();
    }
    if (key.name === 'down' || key.name === 's') {
      currentIndex = Math.min(rows - 1, currentIndex + 1);
      render();
    }
    if (key.name === 'return' || key.name === 'enter') {
      rl.close();
    }
  });

  render();

  return new Promise((resolve) => {
    rl.on('close', () => {
      resolve(options[currentIndex]);
    });
  });
};

module.exports = { createMenu };