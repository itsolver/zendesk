Settings.Tickets.CCs.email_subject: [{{ticket.account}}] Update: {{ticket.title}}
Settings.Tickets.CCs.email_text: |
```
You are registered as a CC on this support request ({{ticket.url}}).
Reply to this email to add a comment to the request.
Please note replies to this email will be CC'd to:
{% capture ccedusers %}{{ ticket.requester.name | append: ' (technical advisor), '}}{% for cc in ticket.ccs %}{% unless forloop.last %}{{ cc.name | append: ', '}}{% else %}{{ cc.name | append: '.'}}{% endunless %}{% endfor %}{% endcapture %}{{ ccedusers | strip_newlines | replace:'&quot','"' | replace:'&lt','<' | replace:'&gt','>' | replace:';','' }}

{{ticket.comments_formatted}}
```