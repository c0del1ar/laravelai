async function sendChatToWebsiteAi(message, history = []) {
  const response = await fetch('/api/ai/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ message, history })
  });

  if (!response.ok) {
    throw new Error('AI request failed');
  }

  return await response.json();
}
