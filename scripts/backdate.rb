# Applied inside the Zammad container after seeding (scripts/reset.sh): Zammad's API stamps everything "now", so
# this moves each ticket's messages and reminder to the hours given in docker/backdate.json, then refreshes the
# ticket's contact times from them.
UserInfo.current_user_id = 1
JSON.parse(STDIN.read).each do |row|
  t = Ticket.find(row['id'])
  arts = Ticket::Article.where(ticket_id: t.id).order(:id).to_a
  arts.zip(row['hours']).each do |a, h|
    next unless a && h
    cols = { created_at: h.hours.ago, updated_at: h.hours.ago }
    # Agent messages were logged by the demo admin; credit them to the ticket's owner.
    cols[:created_by_id] = row['agent'] if a.sender.name == 'Agent' && row['agent']
    a.update_columns(cols)
  end
  cust = arts.select { |a| a.sender.name == 'Customer' }.map(&:created_at).max
  agent = arts.select { |a| a.sender.name == 'Agent' && !a.internal }.map(&:created_at).max
  cols = { created_at: row['hours'].first.hours.ago, updated_at: row['hours'].last.hours.ago,
           last_contact_customer_at: cust, last_contact_agent_at: agent, last_contact_at: [cust, agent].compact.max,
           first_response_at: agent }
  cols[:pending_time] = row['reminder'].hours.from_now if row['reminder']
  cols[:close_at] = row['hours'].last.hours.ago if t.state.name == 'closed'
  t.update_columns(cols)
end
puts 'backdated'
