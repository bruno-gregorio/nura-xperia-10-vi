# Skills Framework

This file details some rules for creation and maintenance of markdown files for skills.

## Entities

Every section in a markdown file, must fit one of the following entities:

### 1. List

We have five kinds of lists:

- The usual unordered markdown list, starting with `-`.
- The usual ordered markdown list, starting with `[0-9]\.` (interpret the regex).
- A titled sequential list, starting with `[0-9]\. **Some Title**` (interpret this loose regex).
- A titled unordered list, starting with `- **Some Title**` (interpret this loose regex).
- A super titled sequential list, starting with a header followed by `[0-9]\. **Some Title**`.

All lists are used for sets of related data. The choice for a list type depends on the amount of content per line and the amount of items, simpler types work best for less content. More complex types should be used less often inside a single file.

### 2. Sectional description

It's a combination fo a header and a short paragraph, must be used to describe the content inside the markdown block.

### 3. Entity description list

A super titled list describing entities that will be referenced in the workflow.

### 4. Steps

Any sequential list describing a series of steps the agent must take to fulfill a request. Basically, the operational description of a workflow.

### 5. Rule list

Any unordered list with rules the agent must keep in mind while running a workflow.

### 6. Exceptions

Any unordered list representing a list of cases that fall off the usual steps for a workflow. Often containing the right way to handle said exceptions.

### 7. Examples

A titled unordered list containing clarifications on how to apply steps and rules to certain cases.

### 8. Linking section

A section with a header, a short description and a link to other file. The description is meant to inform what is relevant to query on that file in the context of the file in which the linking section is present.

### 9. Snippet

A fenced code block (a command, a JSON document, a sample file) attached to what it illustrates: indented under the list item it belongs to, or directly after the sectional description of a section whose purpose is that block. A snippet is never free-standing between paragraphs.

## Directives

- White editing or creating markdown files, the agent might suggest new entities to the framework if it misses the capacity to model something.
- This file should not be edited by the agent without user permission.
- Linking is preferred to redundancy in markdown files.
