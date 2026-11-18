const feedbackForm = document.getElementById('feedback-form');
if (feedbackForm) {
  const feedbackMessage = document.getElementById('feedback-message');
  const feedbackStatus = document.getElementById('feedback-status');
  const sendFeedback = feedbackForm.querySelector('button[type="submit"]');
  let isSending = false;
  const showFeedbackStatus = (message, state) => {
    feedbackStatus.dataset.state = state;
    feedbackStatus.textContent = message;
  };

  feedbackForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (isSending) return;
    const message = feedbackMessage.value.trim();
    if (!message) {
      showFeedbackStatus('请填写反馈内容。', 'error');
      feedbackMessage.focus({preventScroll: true});
      return;
    }

    isSending = true;
    sendFeedback.setAttribute('aria-disabled', 'true');
    feedbackMessage.readOnly = true;
    showFeedbackStatus('正在发送…', 'sending');
    try {
      const response = await fetch('/api/feedback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message}),
      });
      if (response.status === 429) {
        showFeedbackStatus('发送得有点频繁，请稍后再试。', 'error');
      } else if (response.status === 413) {
        showFeedbackStatus('反馈内容太长，请缩短后再发送。', 'error');
      } else if (response.status === 201 && (await response.json()).result === 'saved') {
        feedbackMessage.value = '';
        showFeedbackStatus('反馈提交成功，谢谢你的建议！', 'success');
      } else {
        showFeedbackStatus('反馈发送失败，内容已保留，请稍后重试。', 'error');
      }
    } catch {
      showFeedbackStatus('反馈发送失败，内容已保留，请稍后重试。', 'error');
    } finally {
      feedbackMessage.readOnly = false;
      sendFeedback.removeAttribute('aria-disabled');
      isSending = false;
    }
  });
  sendFeedback.disabled = false;
}
