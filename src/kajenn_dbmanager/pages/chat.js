/** The chat page draws its messages with the core chat renderer. */
import {chatRender} from '@gramlot/gramlot';

export class Logic {
    chatRender(node, params) { return chatRender(this.page, node, params); }
}
