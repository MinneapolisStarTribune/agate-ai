import requests, json, logging, sys
from conf.settings import SLACK_LOG_WEBHOOK_URL

logging.basicConfig(level=logging.INFO)

########## SETUP ##########

class SlackAPIException(Exception):
    '''
    Generic exception to catch Slack errors.
    '''
    pass

########## FUNCTIONS ##########

def post_slack_log_message(message, context, message_type):
    '''
    Posts a message to a designated log channel in Slack. Channel is designated
    by the SLACK_LOG_WEBHOOK_URL environment variable. Requires a webhook be
    set up in Slack with the correct permissions.
    '''

    if not SLACK_LOG_WEBHOOK_URL:
        logging.warning('No Slack webhook URL found. Skipping log message.')
        return

    # Blocks for formatting messages in Slack. See docs:
    # https://api.slack.com/block-kit

    # The block structure to be used if a create post is successful
    create_success_blocks = {
      "blocks": [
        {
          "type": "section",
          "text": {
            "type": "mrkdwn",
            "text": ':white_check_mark: ' + message
          }
        },
        {
          "type": "section",
          "text": {
            "type": "mrkdwn",
            "text": "*Headline:* " + context.get('headline', '')
          }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": context.get('agate_update_msg', '')
                }
            ]
        },
        {
          "type": "actions",
          "elements": [
            {
              "type": "button",
              "text": {
                "type": "plain_text",
                "text": "View payload"
              },
              "url": context.get('storage_url', '')
            },
            {
              "type": "button",
              "text": {
                "type": "plain_text",
                "text": "View article"
              },
              "url": context.get('article_url', '')
            }
          ]
        }
      ]
    }

    # The block structure to be used if a create post is unsuccessful
    create_error_blocks = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ':x: ' + message
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Error:* " + context.get('error_message', '')
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Traceback:*\n```%s```" % str(context.get('traceback', ''))
                }
            }
        ]
    }

    # Format message payload based on message type. Leaving room for
    # new types to be defined here via elifs.
    if message_type == 'create_success':
        payload = create_success_blocks
    elif message_type == 'create_error':
        payload = create_error_blocks

    # Structure payload for Slack API post
    byte_length = str(sys.getsizeof(payload))
    headers = {
        'Content-Type': "application/json",
        'Content-Length': byte_length
    }

    try: # Post to Slack, fail silently with logging
        print(json.dumps(payload))
        response = requests.post(SLACK_LOG_WEBHOOK_URL, 
            data=json.dumps(payload),
            headers=headers)

        if response.status_code != 200:
            raise SlackAPIException(response.status_code, response.text)
    except SlackAPIException as e:
        logging.error('Could not log to Slack. Request failed: %s' % str(e.args[0]))
    except Exception as e:
        logging.error('Could not log to Slack: %s' % str(e.args[0]))
    return