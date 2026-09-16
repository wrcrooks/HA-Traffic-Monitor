# Main Prompt
Generate a Home Assistant add-on that allows the user to select one or more travel routes (e.g. commute from home to work) and monitor the time that driving that route will take as well as traffic conditions

# Additional Requirements
- Route times and traffic conditions should be exposed as objects within Home Assistant
- There should be a UI for the add-on that allows the user to visualize the route with a map
- The user should be able to select their specific route, from multiple routes suggested (a user might not drive the most efficient route every day)
- The add-on should leverage free APIs for pulling traffic information
- There should be an option for the user to select tolls or no tolls as an option/flag for the route
- The user should be able to input their source and destination address for as many routes as they would like