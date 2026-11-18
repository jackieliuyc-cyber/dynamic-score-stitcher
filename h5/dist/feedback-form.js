const feedbackForm = document.getElementById('feedback-form');
if (feedbackForm) {
  const feedbackMessage = document.getElementById('feedback-message');
  const feedbackStatus = document.getElementById('feedback-status');
  const sendFeedback = feedbackForm.querySelector('button[type="submit"]');
  const showFeedbackStatus = (message, error = false) => {
    feedbackStatus.textContent = message;
    feedbackStatus.classList.toggle('feedback-error', error);
    feedbackStatus.hidden = false;
  };

  feedbackForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (sendFeedback.disabled) return;
    const message = feedbackMessage.value.trim();
    if (!message) {
      showFeedbackStatus('请填写反馈内容。', true);
      feedbackMessage.focus();
      return;
    }

    sendFeedback.disabled = true;
    feedbackMessage.readOnly = true;
    showFeedbackStatus('正在发送…');
    try {
      const response = await fetch('/api/feedback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message}),
      });
      if (response.status === 429) {
        showFeedbackStatus('发送得有点频繁，请稍后再试。', true);
      } else if (response.status === 413) {
        showFeedbackStatus('反馈内容太长，请缩短后再发送。', true);
      } else if (response.status === 201 && (await response.json()).result === 'saved') {
        feedbackForm.reset();
        showFeedbackStatus('反馈已发送，谢谢你的建议！');
      } else {
        showFeedbackStatus('反馈发送失败，内容已保留，请稍后重试。', true);
      }
    } catch {
      showFeedbackStatus('反馈发送失败，内容已保留，请稍后重试。', true);
    } finally {
      feedbackMessage.readOnly = false;
      sendFeedback.disabled = false;
    }
  });
}
