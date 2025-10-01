# Text File Input Mode - User Guide

## Overview

The KB article generator now supports **two input modes**:
1. **Zendesk Ticket Search** (original) - Search and analyze Zendesk tickets
2. **Text File Input** (new) - Generate articles from external content like forum posts, Q&A, etc.

## When to Use Text File Input

Use this mode when you have:
- Forum posts from Microsoft Community, Reddit, etc.
- Q&A content from Stack Overflow or similar sites
- Email threads with customer issues and solutions
- Documentation you want to convert to a KB article
- Any structured text with problems and solutions

## Usage

### Command Line
```bash
# From a text file
python generate_kb_from_tickets.py content.txt
python generate_kb_from_tickets.py path/to/article.md

# From Zendesk search (original mode)
python generate_kb_from_tickets.py ctfmon
python generate_kb_from_tickets.py "windows search not working"
```

### Interactive Mode
```bash
python generate_kb_from_tickets.py
# Then enter: content.txt (for file mode)
# Or enter: ctfmon (for search mode)
```

## Text File Format

The parser intelligently detects:
- **Title** - First line of the file
- **Question/Issue** - Content before "Accepted answer" or "Answer:" markers
- **Solutions** - Content after answer markers

### Supported File Types
- `.txt` - Plain text files
- `.md` - Markdown files
- Any file path (detected by `/` or `\` characters)

### Example Input Format

```
How to stop "Intelligent Work" Pop-Up

When I open any office 365 program, a "Intelligent Work" pop-up appears 
in the bottom right corner. I cannot find options to turn it off.

Accepted answer

I believe this is due to the MSI Center software, especially the MSI AI 
Engine feature. To turn off this message, you can:
1. Open MSI Center
2. Open MSI AI Engine feature
3. Click gear icon next to "AI Engine: ON"
4. Uncheck "Show the profile switching animation"

Additional answer

Turning AI off seems to solve that problem.
```

### What Gets Filtered Out

The parser automatically removes:
- Anonymous/username markers
- Date stamps (e.g., "Feb 23, 2024")
- Vote counts ("X people found this helpful")
- Meta text ("Please sign in to rate")
- "I have the same issue" non-solution comments
- "Locked Question" notices

## Output Quality

### Generated Article Example (from content.txt)

**Input:** 888 characters from forum post
**Output:** 7,374 characters professional KB article with:
- Detailed step-by-step instructions
- Keyboard shortcuts in `<kbd>` tags
- Commands in `<code>` tags
- Troubleshooting section
- Registry edits with warnings
- Hardware-specific considerations

**Result:** [Article #13921657550095](https://support.itsolver.net/hc/en-au/articles/13921657550095)

## How It Works

1. **Parse Text File**
   - Reads file content
   - Identifies title, questions, solutions
   - Filters metadata and noise
   - Structures as "ticket-like" data

2. **Generate Article** (same AI process)
   - Uses same Grok AI generation
   - Same quality checks apply
   - Same smart sanitization
   - Minimum 500 characters
   - No generic placeholder content

3. **Upload to Zendesk**
   - AI determines best section
   - Uploads as draft for review
   - Adds appropriate labels

## Comparison: File vs Search Mode

| Feature | Text File Mode | Zendesk Search Mode |
|---------|---------------|---------------------|
| **Input Source** | External content | Zendesk tickets |
| **Data Volume** | Single source | Multiple tickets (up to 10) |
| **Best For** | Forum posts, community Q&A | Internal support patterns |
| **Title Generation** | Uses file's title | Generates from query |
| **Quality Checks** | Same ✓ | Same ✓ |
| **AI Generation** | Same ✓ | Same ✓ |
| **Sanitization** | Applied ✓ | Applied ✓ |

## Tips for Best Results

### 1. Clean Your Input
Remove unnecessary content before processing:
- Navigation elements
- Advertising
- Repeated disclaimers
- Signature blocks

### 2. Structure Matters
Better input format:
```
Clear Title

Problem description paragraph

Answer 1:
Solution steps here

Answer 2:
Alternative solution here
```

### 3. Multiple Solutions
Include 2-4 solution approaches for richer articles:
- Primary solution
- Alternative method
- Troubleshooting tips
- Advanced options

### 4. Technical Details
Include specific technical information:
- Error messages
- Service names
- Registry paths
- Commands
- Software versions

## Troubleshooting

### "Failed to parse text file"
- Check file encoding (should be UTF-8)
- Ensure file exists at path
- Try absolute path: `C:\path\to\file.txt`

### "Generated article is too short"
- Input has too little content
- Add more detail to your text file
- Include multiple solutions/answers

### "Generic placeholder content detected"
- Input lacks specific technical detail
- Add commands, steps, or configuration
- Include error messages or specific symptoms

## Advanced: Custom Text Formats

You can customize the parser for different formats by editing `parse_text_file_content()`:

```python
# Current markers for answers:
['accepted answer', 'answer:', 'solution:', 'reply:']

# Current skip patterns:
['anonymous', 'please sign in', 'people found this', 'locked question']
```

## Examples

### Example 1: Microsoft Community Post
```bash
python generate_kb_from_tickets.py ms-community-post.txt
```
✓ Parsed: 3 solutions found
✓ Generated: 7,374 character article
✓ Uploaded to Microsoft 365 section

### Example 2: Stack Overflow Q&A
Create `stackoverflow.txt`:
```
How to fix Windows Search indexing?

Question: Windows search stopped working after update...

Accepted Answer:
Try rebuilding the search index:
1. Open Control Panel
2. Go to Indexing Options...
```

```bash
python generate_kb_from_tickets.py stackoverflow.txt
```

### Example 3: Internal Documentation
Convert internal troubleshooting notes to KB:
```bash
python generate_kb_from_tickets.py docs/troubleshooting-notes.md
```

## Workflow Integration

### Suggested Workflow
1. **Collect** external content (forum posts, emails)
2. **Save** as `.txt` file with descriptive name
3. **Generate** article: `python generate_kb_from_tickets.py filename.txt`
4. **Review** the draft article in Zendesk
5. **Edit** if needed (add screenshots, links)
6. **Publish** when satisfied

### Batch Processing
For multiple files:
```bash
python generate_kb_from_tickets.py issue1.txt
python generate_kb_from_tickets.py issue2.txt
python generate_kb_from_tickets.py issue3.txt
```

Each generates a separate KB article draft.

## Files Created

For each run, the script creates:
- `kb_article_YYYYMMDD_HHMMSS.html` - Local copy
- Draft article in Zendesk Help Center

Both modes create these files for your records.

## Need Help?

If you encounter issues:
1. Check the console output for quality warnings
2. Review the generated HTML file locally
3. Ensure your text file has clear structure
4. Add more technical detail if article is too generic

The same quality standards apply to both input modes - articles must be high quality or the script will abort.

