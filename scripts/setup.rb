# Run once inside the Zammad container (scripts/up.sh): finish setup without the web wizard, make the demo admin
# (shown as "Claude Connector" on every change it makes) with the generated password, and print an API token for the MCP server.
UserInfo.current_user_id = 1
Setting.set('system_init_done', true)
Setting.set('organization', 'Harbor Trading (SAMPLE)')
Setting.set('product_name', 'Harbor Trading Support (SAMPLE)')
Setting.set('fqdn', 'localhost:8090')
Setting.set('http_type', 'http')
Setting.set('api_token_access', true)
# Zammad's own welcome ticket and its sample customer don't belong in the demo.
Ticket.where(title: 'Help me! I am an example ticket').destroy_all
Organization.where(name: 'Zammad Foundation').each { |o| o.members.each(&:destroy); o.destroy }
login = 'admin@harbor-trading.example'
admin = User.find_by(login: login) || User.create!(
  login: login, email: login, firstname: 'Claude', lastname: 'Connector', password: ENV.fetch('ADMIN_PASSWORD'),
  active: true, roles: Role.where(name: %w[Admin Agent])
)
admin.preferences['intro'] = true  # skip the first-login tour
admin.save!
token = Token.create!(action: 'api', persistent: true, user_id: admin.id, name: 'mojood-mcp',
                      preferences: { permission: %w[admin ticket.agent admin.user admin.organization admin.group] })
puts "TOKEN=#{token.token}"
