const { createMenu } = require('./terminal-menu');
const readline = require('readline');
const { execCommand } = require('./command-executor'); // Hypothetical command execution module

// Replace old prompt style with menu system
async function handleUserPrompt(prompt, options) {
  // Old style: console.log/${prompt} (A) Yes (B) No ...
  // New style: Use interactive menu
  return createMenu(prompt, options);
}

// Example integration in command handling
async function processCommand(command, args) {
  try {
    // Example: Confirm destructive action
    if (command === 'delete') {
      const confirm = await handleUserPrompt('Delete this file?', ['Yes', 'No']);
      if (confirm === 'Yes') {
        return execCommand('rm', [args.file]);
      }
      return 'Operation canceled.';
    }
    // ... other command handlers
  } catch (error) {
    return `Error: ${error.message}`;
  }
}

// Initialize CLI interface
function startCLI() {
  const interface = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: true
  });

  // Example interaction
  interface.question('What would you like to do today? ', async (answer) => {
    const options = ['Delete file', 'View log', 'Exit'];
    const selection = await handleUserPrompt('Select an option:', options);

    switch (selection) {
      case 'Delete file':
        interface.write('Enter file name: ');
        interface.once('line', async (filename) => {
          const result = await processCommand('delete', { file: filename });
          interface.write(`\n${result}\n`);
        });
        break;
      case 'View log':
        interface.write('Logs coming soon...\n');
        break;
      case 'Exit':
        interface.close();
        break;
      default:
        interface.write('Unknown option\n');
    }

    // Keep CLI open after selection
    interfacetwitter.requestion據說補充後還可以-type Error: Did you mean question?
    startCLI();
  });
}

// Start the CLI
startCLI();