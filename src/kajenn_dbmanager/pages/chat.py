"""Natural-language questions on an enrolled database, inside a time-limited session."""

from genro_bag import Bag
from gramlot import endpoint

from kajenn_dbmanager.chat_answers import answer_text, result_table
from kajenn_dbmanager.workbench_page import WorkbenchPage

STATUS = "this.SET('chat.status', {})"
ERROR = STATUS.format('error.message')
class Page(WorkbenchPage):
    title = 'Chat'

    @endpoint
    def open_chat(self, database, **kwargs):
        """Open a query session on an enrolled database."""
        result = self.run('open_session', database=database)
        answer = Bag()
        answer.set_item('session_id', result['session_id'])
        answer.set_item('expires_at', str(result.get('expires_at', '')))
        return answer

    @endpoint
    def close_chat(self, database, session_id, **kwargs):
        self.run('close_session', database=database, session_id=session_id)
        return True

    @endpoint
    def ask(self, database, session_id, question, output='results', **kwargs):
        """Ask one question in the session; return the assistant message and the result table."""
        result = self.run('ask', database=database, session_id=session_id,
                          question=question, output=output)
        answer = Bag()
        answer.set_item('message', answer_text(result))
        answer.set_item('table', result_table(result))
        return answer

    def main(self, root):
        page = root.main(datapath='chat', height='100vh', display='flex',
                         flex_direction='column', padding='8px 12px', gap='8px', min_height=0)
        self.load_profiles(page)
        page.dataSetter('.messages', Bag())
        page.dataSetter('.messageData', Bag())
        page.dataSetter('.output', 'results')
        bar = page.menu(presentation='bar', aria_label='Chat session', padding='4px 8px')
        self.database_select(bar.menuline(group=True), '^chat.database', id='chat-database',
                             disabled='^chat.session:=!!{}')
        session = bar.menuline(group=True)
        session.button('Open session', id='chat-open', disabled='^chat.session:=!!{}').dataRpc(
            'open_chat', database='=chat.database', _onError=ERROR,
            _onResult="this.SET('chat.session', result.getItem('session_id'));"
                      + STATUS.format("'Session open until ' + result.getItem('expires_at')"))
        session.button('Close session', id='chat-close', disabled='^chat.session:=!{}').dataRpc(
            'close_chat', database='=chat.database', session_id='=chat.session', _onError=ERROR,
            _onResult="this.SET('chat.session', null);" + STATUS.format("'Session closed'"))
        messages = page.div(flex='1', min_height=0, overflow='auto')
        view = messages.chatMessages(height='100%', min_height=0, id='chat-messages')
        view.dataController(func='chatRender', messages='^chat.messages', _onBuilt=True)
        composer = page.div(display='flex', gap='8px', align_items='end')
        composer.textBoxArea(value='^.question', rows=2, width='100%', id='chat-question',
                             placeholder='Which states have customers?')
        composer.filteringSelect(value='^.output', values='results:Results,sql:SQL only',
                                 width='9rem', id='chat-output')
        ask = composer.button('Ask', id='chat-ask', disabled='^chat.session:=!{}')
        ask.dataRpc('ask', database='=chat.database', session_id='=chat.session',
                    question='=chat.question', output='=chat.output',
                    _onCalling=STATUS.format("'Asking…'"), _onError=ERROR,
                    _onResult="const m = this.GET('chat.messages'); const t = Date.now().toString(16);"
                              "m.setItem('m_' + t + '0', question, {role: 'user', author: 'You'});"
                              "m.setItem('m_' + t + '1', result.getItem('message'), {role: 'assistant', author: 'DB Manager'});"
                              "this.SET('chat.table', result.getItem('table'));"
                              "this.SET('chat.question', '');" + STATUS.format('null'))
        results = page.details(id='chat-results')
        results.summary('Results of the last answer')
        results.pre('^chat.table', font_family='monospace', max_height='30vh', overflow='auto',
                    margin=0)
        page.p('Up to 100 rows per answer. Rows stay local: later model calls receive questions '
               'and SQL, not results.', class_='muted')
        self.status(page, 'chat.status')
