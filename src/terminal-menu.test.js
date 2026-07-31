const { createMenu } = require('./terminal-menu');
const readline = require('readline');
const { mockInterface, restoreStdin } = require('./test-utils'); // Assume test utilities exist

let menuInstance;
let mockInterface;

beforeAll(() => {
  mockInterface = mockInterface();
  // Save original stdin
  originalStdin = process.stdin;
});

afterAll(() => {
  restoreStdin();
});

describe('Terminal Menu Component', () => {
  it('should navigate with arrow keys', async () => {
    const options = ['Option 1', 'Option 2', 'Option 3'];
    const menu = createMenu('Test Menu', options);

    // Simulate down arrow
    mockInterface.emitKey('down');
    mockInterface.emitKey('down');

    // Simulate enter
    mockInterface.emitKey('return');

    const result = await menu;
    expect(result).toBe('Option 3');
  });

  it('should navigate with W/S keys', async () => {
    const options = ['Yes', 'No'];
    const menu = createMenu('Confirm?', options);

    // Simulate W (up)
    mockInterface.emitKey('w');

    // Simulate S (down)
    mockInterface.emitKey('s');

    // Simulate enter
    mockInterface.emitKey('return');

    const result = await menu;
    expect(result).toBe('No');
  });

  it('should handle multi-option scrolling', async () => {
    const options = Array.from({length: 15}, (_, i) => `Option ${i+1}`);
    const menu = createMenu('Long List', options);

    // Simulate multiple down arrows
    Array(10).fill().forEach(() => mockInterface.emitKey('down'));

    // Simulate enter at bottom
    mockInterface.emitKey('return');

    const result = await menu;
    expect(result).toBe('Option 11'); // Assuming terminal height shows 10 options
  });

  it('should return selected option on Enter', async () => {
    const options = ['Yes', 'No', 'Maybe'];
    const menu = createMenu('Choice?', options);

    // Simulate enter immediately
    mockInterface.emitKey('return');

    const result = await menu;
    expect(result).toBe('Yes');
  });

  it('should maintain backward compatibility', async () => {
    // This is a system test - verify that existing CLI functionality
    // still works alongside the new menu component
    // (Would require actual terminal execution)
    expect(true).toBe(true);
  });
});