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

You contribute to the knowledge base using **Claude Code** (connected to this GitHub repo). No terminal or IDE needed.

### How to Make Changes

Tell Claude Code what you want to update. For example:

- *"Update the leave policy in knowledge_base/hr_admin/policies.md to add the new maternity leave policy"*
- *"Add information about the Aarey centre timings to knowledge_base/helpdesk/"*
- *"Fix the salary deduction rules in knowledge_base/hr_admin/payroll.md"*

Claude Code will edit the file, create a branch, and push the changes. Sundar will review and approve.

### Writing Guidelines

- **Use simple Hindi** - the same way you'd explain it to a colleague
- **Keep it short** - target 20-40 seconds when read aloud
- **Focus on what workers actually ask** - practical, not theoretical
- Use headings (`##`) to organize topics
- Use bullet points for steps

### Example Entry

```markdown
## Leave Request Kaise Kare?

1. Pehle team lead ko WhatsApp/call karo
2. Reason batao (sick/planned/emergency)
3. Jaldi message karo - late mat karo
4. Calendar me mark hoga automatically
```

### Important Notes

- **shared/** files are used by ALL domains - edit carefully
- **Domain folders** (hr_admin, helpdesk, production) are specific to each use case
- Changes take effect on next bot restart
