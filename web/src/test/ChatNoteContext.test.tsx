import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AIContextItem, ChatMessage } from '../types';
import { ChatPane } from '../components/chat/ChatPane';

describe('personal note chat context', () => {
  it('sends only included linked personal note IDs for a live message', async () => {
    const onSendMessage = vi.fn().mockResolvedValue(undefined);
    const contextItems: AIContextItem[] = [
      { id: 'note-one', personalNoteId: 'personal-1', kind: 'note', title: 'Included note', detail: 'linked workspace note', tokens: 12, included: true },
      { id: 'note-two', personalNoteId: 'personal-2', kind: 'note', title: 'Excluded note', detail: 'linked workspace note', tokens: 10, included: false },
      { id: 'thread', kind: 'turn', title: 'Current chat', detail: 'conversation', tokens: 20, included: true },
    ];

    render(
      <ChatPane
        projectName="AURA"
        threadTitle="Live chat"
        messages={[] as ChatMessage[]}
        onMessagesChange={() => undefined}
        contextItems={contextItems}
        onSendMessage={onSendMessage}
        isLiveThread
      />,
    );

    fireEvent.change(screen.getByPlaceholderText('Ask AURA in this chat…'), { target: { value: 'Use the linked note.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(onSendMessage).toHaveBeenCalledWith('Use the linked note.', undefined, ['personal-1']));
  });
});
