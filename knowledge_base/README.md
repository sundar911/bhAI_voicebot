# Knowledge Base

This directory contains all the domain knowledge that bhAI uses to answer employee questions.

## Structure

```
knowledge_base/
├── shared/                 # Used by ALL domains
│   ├── company_overview.md # Tiny Miracles mission, values, basics
│   ├── escalation_policy.md # When to escalate to human
│   └── style_guide.md      # How to respond (tone, length, structure)
│
├── hr_admin/               # HR-Admin domain (ACTIVE)
│   ├── policies.md         # Leave, attendance, conduct policies
│   ├── payroll.md          # Salary, deductions, bonuses
│   └── benefits.md         # Support programs, health, childcare
│
├── helpdesk/               # Helpdesk domain (FUTURE)
│   └── .gitkeep            # Govt schemes, document help
│
└── production/             # Production domain (FUTURE)
    └── .gitkeep            # Factory floor, machines, chai/breakfast
```

## For Tiny Miracles Team

### Adding/Editing Content

1. **Edit existing files** directly in VS Code or any text editor
2. **Use simple Hindi** - the same style workers understand
3. **Keep it practical** - focus on what workers actually ask
4. **Save and commit** your changes

### File Format

- Use Markdown (.md) files
- Use headings (`##`) to organize topics
- Use bullet points for lists
- Keep paragraphs short

### Example Entry

```markdown
## Leave Request Kaise Kare?

1. Pehle team lead ko WhatsApp/call karo
2. Reason batao (sick/planned/emergency)
3. Jaldi message karo - late mat karo
4. Calendar me mark hoga automatically
```

### Important Notes

- **shared/** files are used by ALL bots - edit carefully
- **Domain folders** (hr_admin, helpdesk, production) are specific to each use case
- Changes take effect on next bot restart
- Test your changes before pushing to production
