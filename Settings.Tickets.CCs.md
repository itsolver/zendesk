Settings.Tickets.CCs.email_subject: [{{ticket.account}}] Update: {{ticket.title}}
Settings.Tickets.CCs.email_text: |
```
You are registered as a CC on this support request ({{ticket.url}}).
Reply to this email to add a comment to the request.
Please note replies to this email will be CC'd to:
{% capture ccedusers %}{{ ticket.requester.name | prepend: '"' | append: '" '}} {{ticket.requester.email | prepend:'<' | append: '>, ' }}{% for cc in ticket.ccs %}{% unless forloop.last %}{{ cc.name | prepend: '"' | append: '" '}} {{ cc.email | prepend:'<' | append: '>, ' }}{% else %}{{ cc.name | prepend: '"' | append: '" '}} {{ cc.email | prepend:'<' | append: '>' }}{% endunless %}{% endfor %}{% endcapture %}{{ ccedusers | strip_newlines | replace:'&quot','"' | replace:'&lt','<' | replace:'&gt','>' | replace:';','' }}

{{ticket.comments_formatted}}
```