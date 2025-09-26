#!/usr/bin/env node

/**
 * Node.js script to remove JSON files where "active" field is false
 * Author: Generated for IT Solver customer support project
 * Usage: node remove_inactive_json.js [path] [--dry-run] [--verbose]
 */

const fs = require('fs').promises;
const path = require('path');
const readline = require('readline');

// Parse command line arguments
const args = process.argv.slice(2);
const targetPath = args.find(arg => !arg.startsWith('--')) || './zendesk-support-assets';
const isDryRun = args.includes('--dry-run');
const isVerbose = args.includes('--verbose');

// Function to check if a JSON file has active: false
async function isInactiveJsonFile(filePath) {
    try {
        const content = await fs.readFile(filePath, 'utf8');
        const json = JSON.parse(content);
        
        // Check if the JSON object has an "active" property set to false
        return json.hasOwnProperty('active') && json.active === false;
    } catch (error) {
        if (isVerbose) {
            console.warn(`Failed to parse JSON file: ${filePath} - ${error.message}`);
        }
        return false;
    }
}

// Function to recursively find all JSON files
async function findJsonFiles(dir) {
    const files = [];
    
    try {
        const entries = await fs.readdir(dir, { withFileTypes: true });
        
        for (const entry of entries) {
            const fullPath = path.join(dir, entry.name);
            
            if (entry.isDirectory()) {
                const subFiles = await findJsonFiles(fullPath);
                files.push(...subFiles);
            } else if (entry.isFile() && entry.name.endsWith('.json')) {
                files.push(fullPath);
            }
        }
    } catch (error) {
        console.error(`Error reading directory ${dir}: ${error.message}`);
    }
    
    return files;
}

// Function to prompt user for confirmation
function askConfirmation(question) {
    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout
    });
    
    return new Promise((resolve) => {
        rl.question(question, (answer) => {
            rl.close();
            resolve(answer.toLowerCase() === 'y' || answer.toLowerCase() === 'yes');
        });
    });
}

// Main function
async function main() {
    console.log(`\x1b[32mScanning for JSON files with active: false in path: ${targetPath}\x1b[0m`);
    
    try {
        // Check if path exists
        await fs.access(targetPath);
    } catch (error) {
        console.error(`Path does not exist: ${targetPath}`);
        process.exit(1);
    }
    
    // Find all JSON files
    const jsonFiles = await findJsonFiles(targetPath);
    
    if (jsonFiles.length === 0) {
        console.log('\x1b[33mNo JSON files found in the specified path.\x1b[0m');
        process.exit(0);
    }
    
    console.log(`\x1b[36mFound ${jsonFiles.length} JSON files to check...\x1b[0m`);
    
    const inactiveFiles = [];
    
    // Check each JSON file
    for (const file of jsonFiles) {
        if (isVerbose) {
            console.log(`\x1b[90mChecking: ${file}\x1b[0m`);
        }
        
        if (await isInactiveJsonFile(file)) {
            inactiveFiles.push(file);
            if (isVerbose) {
                console.log(`  \x1b[33m→ Found inactive file: ${path.basename(file)}\x1b[0m`);
            }
        }
    }
    
    if (inactiveFiles.length === 0) {
        console.log('\x1b[32mNo JSON files with active: false found.\x1b[0m');
        process.exit(0);
    }
    
    console.log(`\n\x1b[31mFound ${inactiveFiles.length} files with active: false:\x1b[0m`);
    inactiveFiles.forEach(file => {
        console.log(`  \x1b[31m- ${file}\x1b[0m`);
    });
    
    if (isDryRun) {
        console.log(`\n\x1b[35m[DRY-RUN] Would delete ${inactiveFiles.length} files\x1b[0m`);
        console.log('\x1b[35mRun without --dry-run to actually delete the files.\x1b[0m');
    } else {
        const confirmed = await askConfirmation('\n\x1b[33mProceed with deletion? (y/N): \x1b[0m');
        
        if (confirmed) {
            let deletedCount = 0;
            for (const file of inactiveFiles) {
                try {
                    await fs.unlink(file);
                    console.log(`\x1b[32mDeleted: ${path.basename(file)}\x1b[0m`);
                    deletedCount++;
                } catch (error) {
                    console.error(`\x1b[31mFailed to delete ${file}: ${error.message}\x1b[0m`);
                }
            }
            console.log(`\n\x1b[32mSuccessfully deleted ${deletedCount} files.\x1b[0m`);
        } else {
            console.log('\x1b[33mOperation cancelled.\x1b[0m');
        }
    }
}

// Run the script
main().catch(error => {
    console.error(`\x1b[31mScript error: ${error.message}\x1b[0m`);
    process.exit(1);
});
