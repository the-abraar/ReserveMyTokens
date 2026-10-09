import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CoordinatorClient:
    def __init__(self, coordinator_url: str, poll_interval: int):
        self.coordinator_url = coordinator_url
        self.poll_interval = poll_interval

    def start_polling(self, ollama_adapter):
        logger.info(f"Connecting to coordinator at {self.coordinator_url}")
        
        try:
            while True:
                logger.info("Polling for jobs...")
                # Mock polling
                job = self._mock_poll_job()
                if job:
                    logger.info(f"Received job: {job}")
                    result = ollama_adapter.run_inference(job['model'], job['prompt'])
                    logger.info(f"Inference result: {result}")
                    self._mock_submit_result(job['job_id'], result)
                else:
                    logger.info("No jobs available.")
                
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Stopping polling...")

    def _mock_poll_job(self):
        # Mocking receiving a job occasionally
        import random
        if random.random() > 0.5:
            return {
                "job_id": "job_123",
                "model": "llama2",
                "prompt": "Hello, world!"
            }
        return None

    def _mock_submit_result(self, job_id, result):
        logger.info(f"Submitting result for {job_id} to {self.coordinator_url}")
        pass
